import json
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from api.llm.client import LLMClient, StructuredOutputError
from api.llm.pricing import cost_usd
from api.llm.tracing import TraceRecord


class Answer(BaseModel):
    value: int


def completion(content: str, prompt_tokens: int = 100, completion_tokens: int = 20) -> Any:
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class FakeProvider:
    """Returns queued replies and records request bodies."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[Any] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return httpx2.Response(200, json=completion(self.replies.pop(0)))


def make_client(provider: FakeProvider, traces: list[TraceRecord]) -> LLMClient:
    async def tracer(record: TraceRecord) -> None:
        traces.append(record)

    return LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        prices={"m": (1.0, 4.0)},
        tracer=tracer,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)),
    )


def test_cost() -> None:
    assert cost_usd({"m": (1.0, 4.0)}, "m", 1_000_000, 500_000) == Decimal(3)
    assert cost_usd({}, "free-model", 1000, 1000) == 0


async def test_complete_is_traced() -> None:
    traces: list[TraceRecord] = []
    client = make_client(FakeProvider(["hello"]), traces)

    result = await client.complete([{"role": "user", "content": "hi"}], step="t", project_id=7)

    assert result.text == "hello"
    assert (result.input_tokens, result.output_tokens) == (100, 20)
    assert result.cost_usd == Decimal("0.00018")
    assert len(traces) == 1
    assert traces[0].project_id == 7 and traces[0].step == "t"


async def test_structured_retries_with_validation_error() -> None:
    provider = FakeProvider(['{"value": "not a number"}', '```json\n{"value": 42}\n```'])
    traces: list[TraceRecord] = []
    client = make_client(provider, traces)

    result = await client.complete_structured([{"role": "user", "content": "q"}], Answer, step="s")

    assert result.parsed == Answer(value=42)
    assert len(traces) == 2
    assert result.input_tokens == 200  # summed over both attempts
    retry_messages = provider.requests[1]["messages"]
    assert "did not match the required JSON schema" in retry_messages[-1]["content"]
    assert provider.requests[0]["response_format"]["type"] == "json_schema"


async def test_structured_gives_up() -> None:
    client = make_client(FakeProvider(["nope"] * 3), [])
    with pytest.raises(StructuredOutputError):
        await client.complete_structured([{"role": "user", "content": "q"}], Answer, step="s")
