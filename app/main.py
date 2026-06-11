import os
import time
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import AgentOrchestrator
from app.config import settings
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware
import os as _os
import os

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("agent.api")


# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Agent service starting — model=%s", settings.model)
    app.state.orchestrator = AgentOrchestrator()
    app.state.start_time = time.time()
    yield
    logger.info("🛑 Agent service shutting down")



# App
app = FastAPI(
    title="Mini AI Agent",
    description="A production-grade AI agent with tool-use, structured reasoning, and observability.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)
app.add_middleware(RequestLoggingMiddleware)

# Serve static UI
_static_dir = _os.path.join(_os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# Schemas

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4096, description="Natural-language question for the agent")
    session_id: str | None = Field(None, description="Optional session ID for multi-turn context")
    stream: bool = Field(False, description="Reserved for future streaming support")


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any]
    output: Any


class AskResponse(BaseModel):
    request_id: str
    session_id: str
    answer: str
    reasoning_steps: list[str]
    tools_used: list[ToolCall]
    latency_ms: float
    model: str
    tokens_used: int | None = None


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    model: str
    version: str


# Routes
@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health(request: Request):
    uptime = time.time() - request.app.state.start_time
    return HealthResponse(
        status="ok",
        uptime_seconds=round(uptime, 2),
        model=settings.model,
        version="1.0.0",
    )


@app.get("/", tags=["ops"], include_in_schema=False)
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.post("/ask", response_model=AskResponse, tags=["agent"])
async def ask(body: AskRequest, request: Request):
    request_id = str(uuid.uuid4())
    session_id = body.session_id or str(uuid.uuid4())

    logger.info("request_id=%s  session=%s  question=%r", request_id, session_id, body.question[:80])

    t0 = time.perf_counter()
    try:
        result = await request.app.state.orchestrator.run(
            question=body.question,
            session_id=session_id,
            request_id=request_id,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="LLM call timed out")
    except Exception as exc:
        logger.exception("Agent error request_id=%s", request_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    latency_ms = (time.perf_counter() - t0) * 1000
    logger.info("request_id=%s  latency_ms=%.1f  tools=%d", request_id, latency_ms, len(result["tools_used"]))

    return AskResponse(
        request_id=request_id,
        session_id=session_id,
        answer=result["answer"],
        reasoning_steps=result["reasoning_steps"],
        tools_used=[ToolCall(**t) for t in result["tools_used"]],
        latency_ms=round(latency_ms, 2),
        model=settings.model,
        tokens_used=result.get("tokens_used"),
    )

# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )