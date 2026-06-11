import asyncio
import json
import logging
from typing import Any

import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool

from app.config import settings
from app.tools import TOOLS, dispatch_tool

logger = logging.getLogger("agent.orchestrator")

SYSTEM_PROMPT = """You are a precise, expert AI assistant with access to a set of tools.

When answering:
1. Think step-by-step before using a tool.
2. Use tools only when they genuinely help answer the question.
3. After receiving tool results, synthesise a clear, direct answer.
4. Never fabricate tool results, only use what the tools return.
5. Be concise but thorough.
"""


def _build_gemini_tools() -> list[Tool]:
    declarations = []
    for t in TOOLS:
        declarations.append(
            FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["input_schema"].copy(),
            )
        )
    return [Tool(function_declarations=declarations)]


class AgentOrchestrator:
    def __init__(self):
        if settings.enable_stub or not settings.gemini_api_key:
            self._model = None
            logger.warning("Running in STUB mode, no LLM calls will be made")
        else:
            genai.configure(api_key=settings.gemini_api_key)
            self._gemini_tools = _build_gemini_tools()
            self._model = genai.GenerativeModel(
                model_name=settings.model,
                system_instruction=SYSTEM_PROMPT,
                tools=self._gemini_tools,
            )
            logger.info("Gemini model initialised — model=%s", settings.model)

    async def run(self, question: str, session_id: str, request_id: str) -> dict[str, Any]:
        if self._model is None:
            return await self._stub_response(question)

        # Gemini SDK is synchronous — offload to thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_run, question, session_id, request_id
        )

    def _sync_run(self, question: str, session_id: str, request_id: str) -> dict[str, Any]:
        chat = self._model.start_chat()
        reasoning_steps: list[str] = []
        tools_used: list[dict] = []
        tokens_used: int = 0
        iteration = 0
        current_message = question

        while iteration < settings.max_tool_iterations:
            iteration += 1
            reasoning_steps.append(f"[Iteration {iteration}] Calling Gemini…")

            response = chat.send_message(current_message)
            candidate = response.candidates[0]

            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens_used += getattr(response.usage_metadata, "total_token_count", 0)

            # Collect parts
            function_call_parts = []
            text_parts = []
            for part in candidate.content.parts:
                if part.function_call.name:
                    function_call_parts.append(part.function_call)
                elif part.text:
                    text_parts.append(part.text)

            # Final answer - no tool calls requested
            if not function_call_parts:
                final_answer = " ".join(text_parts).strip() or "I was unable to produce a response."
                reasoning_steps.append(f"[Iteration {iteration}] Final answer produced.")
                return {
                    "answer": final_answer,
                    "reasoning_steps": reasoning_steps,
                    "tools_used": tools_used,
                    "tokens_used": tokens_used,
                }

            # Dispatch tools - sync, direct call, no asyncio needed
            reasoning_steps.append(
                f"[Iteration {iteration}] Invoking {len(function_call_parts)} tool(s): "
                + ", ".join(fc.name for fc in function_call_parts)
            )

            tool_results = [
                dispatch_tool(fc.name, dict(fc.args))
                for fc in function_call_parts
            ]

            for fc, result in zip(function_call_parts, tool_results):
                tools_used.append({"name": fc.name, "input": dict(fc.args), "output": result})
                reasoning_steps.append(f"  Tool '{fc.name}' → {json.dumps(result)[:200]}")

            # Feed results back to Gemini
            function_response_parts = [
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
                for fc, result in zip(function_call_parts, tool_results)
            ]
            current_message = function_response_parts  # type: ignore[assignment]

        reasoning_steps.append("[Max iterations reached]")
        return {
            "answer": "The agent reached the maximum number of reasoning steps without a final answer.",
            "reasoning_steps": reasoning_steps,
            "tools_used": tools_used,
            "tokens_used": tokens_used,
        }

    async def _stub_response(self, question: str) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        q = question.lower()
        if any(op in q for op in ["+", "-", "*", "/", "calculate", "compute", "what is"]):
            stub_answer = "STUB MODE: Would call the `calculator` tool via the Gemini function-calling loop."
            tools_used = [{"name": "calculator", "input": {"expression": "..."}, "output": {"result": "STUB"}}]
        elif "time" in q or "date" in q:
            stub_answer = "STUB MODE: Would call `get_current_datetime` tool."
            tools_used = [{"name": "get_current_datetime", "input": {}, "output": {"datetime": "STUB"}}]
        else:
            stub_answer = (
                f"STUB MODE: Set GEMINI_API_KEY to enable real agent reasoning. "
                f"Your question: «{question}»"
            )
            tools_used = []

        return {
            "answer": stub_answer,
            "reasoning_steps": ["[Stub mode - no LLM call]"],
            "tools_used": tools_used,
            "tokens_used": None,
        }