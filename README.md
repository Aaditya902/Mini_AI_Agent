# Mini AI Agent System

A production-grade AI agent service built with **FastAPI** + **Google Gemini** (function-calling) running inside **Docker**. The agent follows a **ReAct** (Reason → Act → Observe) loop, it reasons about the question, picks tools, executes them, and repeats until it produces a final answer.

A built-in **chat UI** is served directly from the same container, accessible at `http://localhost:8000` the moment you run Docker Compose.

---

## Architecture

```
Browser (http://localhost:8000)
         │
         │  POST /ask {"question": "..."}
         ▼
┌─────────────────────────────────────────────────┐
│  FastAPI  (Gunicorn + UvicornWorker × 2)         │
│  ├── RateLimitMiddleware  (60 req/min per IP)    │
│  ├── RequestLoggingMiddleware                    │
│  ├── GET  /          → Chat UI (index.html)      │
│  ├── GET  /health    → Health check              │
│  ├── GET  /docs      → Auto API docs             │
│  └── POST /ask       → AgentOrchestrator         │
│                            │                     │
│                   ┌────────▼────────┐            │
│                   │   Gemini API    │            │
│                   │ (function-call) │            │
│                   └────────┬────────┘            │
│                            │ tool calls           │
│                   ┌────────▼──────────────────┐  │
│                   │     Tool Dispatcher        │  │
│                   │  calculator  │  datetime   │  │
│                   │  word_count  │  unit_conv  │  │
│                   │         json_fmt           │  │
│                   └───────────────────────────-┘  │
└─────────────────────────────────────────────────┘
```

### Agent ReAct Loop

```
Question ──► [Gemini] ──► function_call? ──YES──► [tool dispatch]
                │                                       │
               NO                             result fed back
                │                                       │
           final answer ◄────────── [Gemini] ◄──────────┘
```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- A Google Gemini API key

```bash
# 1. Clone and configure
git clone https://github.com/you/mini-ai-agent
cd mini-ai-agent
cp .env.example .env
# Edit .env - add your GEMINI_API_KEY

# 2. Build and run
docker compose up --build

# 3. Open the chat UI
# http://localhost:8000
```

### Demo / Stub mode (no API key required)

```bash
ENABLE_STUB=true docker compose up --build
```

---

## Project Structure

```
mini-ai-agent/
├── app/
│   ├── main.py          # FastAPI app - routes, lifespan, middleware setup
│   ├── agent.py         # AgentOrchestrator - Gemini ReAct loop
│   ├── tools.py         # 5 tool implementations + registry
│   ├── middleware.py    # Rate limiting + request logging
│   ├── config.py        # Pydantic settings from environment variables
│   └── static/
│       └── index.html   # Chat UI - served at http://localhost:8000
├── tests/
│   └── test_agent.py    # 17 pytest tests (runs in stub mode)
├── Dockerfile           # Multi-stage build, non-root user, HEALTHCHECK
├── docker-compose.yml   # Local development
├── k8s.yaml             # Kubernetes: Deployment + HPA + Ingress + Secret
├── requirements.txt
└── .env.example
```

---

## API Reference

### `POST /ask`

The core agent endpoint.

```json
// Request
{
  "question": "Convert 100 km to miles and what time is it in UTC?",
  "session_id": "optional-uuid-for-multi-turn"
}

// Response
{
  "request_id": "f3a2...",
  "session_id": "abc123",
  "answer": "100 km equals 62.14 miles. The current UTC time is 2026-05-15T11:50:20Z.",
  "reasoning_steps": [
    "[Iteration 1] Calling Gemini…",
    "[Iteration 1] Invoking 2 tool(s): unit_converter, get_current_datetime",
    "  Tool 'unit_converter' → {\"output\": \"62.1371 miles\"}",
    "  Tool 'get_current_datetime' → {\"datetime\": \"2026-05-15T11:50:20Z\"}",
    "[Iteration 2] Calling Gemini…",
    "[Iteration 2] Final answer produced."
  ],
  "tools_used": [
    {"name": "unit_converter", "input": {"value": 100, "from_unit": "km", "to_unit": "miles"}, "output": {...}},
    {"name": "get_current_datetime", "input": {"format": "iso"}, "output": {...}}
  ],
  "latency_ms": 1423.7,
  "model": "gemini-2.5-flash",
  "tokens_used": 847
}
```

### `GET /health`

```json
{"status": "ok", "uptime_seconds": 142.3, "model": "gemini-2.5-flash", "version": "1.0.0"}
```

### `GET /`

Serves the chat UI.

### `GET /docs`

Auto-generated interactive API documentation (Swagger UI).

---

## Available Tools

| Tool | Description | Example input |
|------|-------------|---------------|
| `calculator` | Evaluates math expressions safely | `"1337 * 42"` |
| `get_current_datetime` | Returns current UTC date/time | - |
| `word_counter` | Counts words, chars, sentences in text | any text |
| `unit_converter` | km↔miles, kg↔lbs, °C↔°F, m↔ft | `100 km → miles` |
| `json_formatter` | Parses and pretty-prints JSON | raw JSON string |

Adding a new tool takes ~15 lines: write a sync function, add its JSON-schema entry to `TOOLS`, register it in `TOOL_FN_MAP`.


## Running Tests

```bash
pip install -r requirements.txt
ENABLE_STUB=true GEMINI_API_KEY="" pytest tests/ -v
# 17 passed
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | `""` | Your Google Gemini API key |
| `MODEL` | `gemini-2.5-flash` | Gemini model to use |
| `MAX_TOKENS` | `1024` | Max tokens per LLM response |
| `MAX_TOOL_ITERATIONS` | `5` | Max ReAct loop iterations |
| `ENABLE_STUB` | `false` | Skip real LLM calls (demo mode) |
| `LOG_LEVEL` | `info` | Logging level |

---

## How It Scales in Kubernetes

See `k8s.yaml` for the full manifest. Key decisions:

**Horizontal scaling** - the service is completely stateless. Every replica can handle any request. HPA scales from 2 → 10 pods based on CPU utilisation (target 60%).

**Zero-downtime deploys** - `RollingUpdate` with `maxUnavailable: 0` ensures no requests are dropped during deploys.

**Rate limiting at scale** - the current in-process sliding-window rate limiter works per replica. With multiple replicas, swap it for a Redis-backed limiter (`fastapi-limiter`) so all pods share one counter.

**LLM call management** - Gemini calls take 1–5s each. At scale, move to an async job queue (Celery + Redis) so the HTTP layer returns a job ID immediately and the client polls for the result.

**Observability** - Prometheus scrape annotations on pods, structured JSON logs, `X-Response-Time-Ms` header on every response.

---

## What Would Break First Under Load

1. **Gemini API rate limits (RPM/TPM)** - each request holds a connection open for 1–5s. At ~20–30 concurrent users you'll hit Google's rate limits first. Fix: retry with exponential backoff (already in the SDK) + request queue.

2. **In-process rate limiter** - doesn't sync across replicas. Fix: Redis-backed distributed limiter.

3. **Gunicorn worker pool** - 2 workers × async coroutines. If Gemini is slow, the thread pool (used for the sync Gemini SDK) fills up. Fix: increase workers or move to a full async Gemini client.

4. **Memory** - conversation message list grows with each tool iteration. Fix: already capped at 5 iterations; for longer conversations, compress or truncate old messages.

