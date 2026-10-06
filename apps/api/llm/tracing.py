from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from api.db.models import LLMCall
from api.db.session import get_sessionmaker


@dataclass(frozen=True)
class TraceRecord:
    step: str
    model: str
    prompt_version: str | None
    project_id: int | None
    eval_run_id: int | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    request_json: Any
    response_json: Any


Tracer = Callable[[TraceRecord], Awaitable[None]]


async def db_tracer(record: TraceRecord) -> None:
    """Store one LLM call in llm_calls."""
    async with get_sessionmaker()() as session:
        session.add(LLMCall(**asdict(record)))
        await session.commit()


async def null_tracer(record: TraceRecord) -> None:
    return None
