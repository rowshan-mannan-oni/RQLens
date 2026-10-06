"""Provider-neutral LLM client over the OpenAI-compatible chat completions protocol.

Works with Gemini, Groq, OpenRouter, Ollama, or OpenAI by changing LLM_BASE_URL and LLM_MODEL.
Retries on 429, 5xx, and timeouts are handled by the SDK with exponential backoff.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx2
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ValidationError

from api.config import get_settings
from api.llm.pricing import cost_usd
from api.llm.tracing import Tracer, TraceRecord, db_tracer

Message = Mapping[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text as the model wrote it


class StructuredOutputError(Exception):
    """The model did not return output matching the schema after all attempts."""


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    text: str
    parsed: T | None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    tool_calls: tuple[ToolCall, ...] = ()
    # The assistant message as returned, to append to the conversation. Provider-specific
    # fields (such as Gemini thought signatures on tool calls) are kept.
    message: dict[str, Any] | None = None


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        prices: Mapping[str, tuple[float, float]] | None = None,
        tracer: Tracer = db_tracer,
        http_client: httpx2.AsyncClient | None = None,
        embedding_model: str = "",
    ) -> None:
        self.model = model
        self.embedding_model = embedding_model
        self._prices = prices or {}
        self._tracer = tracer
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "unset",
            timeout=timeout_s,
            max_retries=max_retries,
            http_client=http_client,
        )

    @classmethod
    def from_settings(cls, tracer: Tracer = db_tracer) -> "LLMClient":
        s = get_settings()
        return cls(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
            timeout_s=s.llm_timeout_s,
            max_retries=s.llm_max_retries,
            prices=s.llm_prices,
            tracer=tracer,
            embedding_model=s.llm_embedding_model,
        )

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        step: str,
        model: str | None = None,
        prompt_version: str | None = None,
        project_id: int | None = None,
        eval_run_id: int | None = None,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResult[BaseModel]:
        """One chat completion, traced. Failed calls are traced too, then re-raised."""
        model = model or self.model
        request: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if response_format is not None:
            request["response_format"] = response_format
        if tools:
            request["tools"] = list(tools)
            if tool_choice is not None:
                request["tool_choice"] = tool_choice

        def trace(**fields: Any) -> TraceRecord:
            return TraceRecord(
                step=step,
                model=model,
                prompt_version=prompt_version,
                project_id=project_id,
                eval_run_id=eval_run_id,
                request_json=request,
                **fields,
            )

        started = time.perf_counter()
        try:
            response = cast(ChatCompletion, await self._client.chat.completions.create(**request))
        except Exception as exc:
            await self._tracer(
                trace(
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=Decimal(0),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    response_json={"error": f"{type(exc).__name__}: {exc}"},
                )
            )
            raise
        latency_ms = round((time.perf_counter() - started) * 1000)

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        cost = cost_usd(self._prices, model, input_tokens, output_tokens)
        choice = response.choices[0].message if response.choices else None
        text = (choice.content or "") if choice else ""
        tool_calls = tuple(
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (choice.tool_calls or [] if choice else [])
            if c.type == "function"
        )

        await self._tracer(
            trace(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
                response_json=response.model_dump(mode="json"),
            )
        )
        return LLMResult(
            text=text,
            parsed=None,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            message=choice.model_dump(mode="json", exclude_none=True) if choice else None,
        )

    async def embed(
        self,
        texts: Sequence[str],
        *,
        step: str,
        project_id: int | None = None,
        eval_run_id: int | None = None,
    ) -> list[list[float]]:
        """Embedding vectors for `texts`, in order. Traced like completions (texts not stored)."""
        if not self.embedding_model:
            raise ValueError("No embedding model is configured (LLM_EMBEDDING_MODEL).")
        started = time.perf_counter()

        async def trace(input_tokens: int, response: Any) -> None:
            await self._tracer(
                TraceRecord(
                    step=step,
                    model=self.embedding_model,
                    prompt_version=None,
                    project_id=project_id,
                    eval_run_id=eval_run_id,
                    input_tokens=input_tokens,
                    output_tokens=0,
                    cost_usd=cost_usd(self._prices, self.embedding_model, input_tokens, 0),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    request_json={"model": self.embedding_model, "inputs": len(texts)},
                    response_json=response,
                )
            )

        try:
            response = await self._client.embeddings.create(
                model=self.embedding_model, input=list(texts)
            )
        except Exception as exc:
            await trace(0, {"error": f"{type(exc).__name__}: {exc}"})
            raise
        tokens = response.usage.prompt_tokens if response.usage else 0
        await trace(tokens, {"vectors": len(response.data)})
        ordered = sorted(response.data, key=lambda d: d.index)
        return [list(d.embedding) for d in ordered]

    async def complete_structured[T: BaseModel](
        self,
        messages: Sequence[Message],
        schema: type[T],
        *,
        step: str,
        max_attempts: int = 3,
        **kwargs: Any,
    ) -> LLMResult[T]:
        """Completion parsed into `schema`. On invalid output, retry with the error appended.

        Token counts and cost in the result cover all attempts.
        """
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        conversation: list[Message] = list(messages)
        input_tokens = output_tokens = latency_ms = 0
        cost = Decimal(0)
        error = ""

        for _ in range(max_attempts):
            result = await self.complete(
                conversation, step=step, response_format=response_format, **kwargs
            )
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            cost += result.cost_usd
            latency_ms += result.latency_ms
            try:
                parsed = schema.model_validate_json(_strip_code_fence(result.text))
            except ValidationError as exc:
                error = str(exc)
                conversation += [
                    {"role": "assistant", "content": result.text},
                    {
                        "role": "user",
                        "content": "Your reply did not match the required JSON schema:\n"
                        f"{error}\nReply again with only valid JSON matching the schema.",
                    },
                ]
                continue
            return LLMResult(
                text=result.text,
                parsed=parsed,
                model=result.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                latency_ms=latency_ms,
            )

        raise StructuredOutputError(
            f"{schema.__name__}: no valid output after {max_attempts} attempts. Last error: {error}"
        )


def _strip_code_fence(text: str) -> str:
    """Some providers wrap JSON in ```json fences even when asked for a schema."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.removesuffix("```").strip()
    return stripped
