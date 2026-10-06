"""Bounded tool loop for one chat question.

The model calls tools until it calls `final_answer`. Limits: tool calls, failed queries,
tokens and wall-clock time. When a limit is reached the model gets one last turn in which only
`final_answer` is offered. A final answer whose numbers do not appear in any tool result is
sent back once for correction; if it still fails it is returned with a grounding flag.
"""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from openai import RateLimitError

from api.agent import grounding
from api.agent.tools import FINAL_ONLY, TOOL_SPECS, ToolBox
from api.llm.client import LLMClient, Message, ToolCall

PROMPT_VERSION = "chat_agent.v1"
PROMPT = (Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)
HISTORY_MESSAGES = 10
RETRY_IN = re.compile(r"retry in (?:(\d+)m)?([\d.]+)s", re.IGNORECASE)
SCHEMA_IN_PROMPT_CHARS = 30_000


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 12
    max_sql_errors: int = 3
    token_budget: int = 200_000
    time_budget_s: float = 240.0
    # Free tiers limit requests per minute; wait out a limit this short, up to this many times.
    rate_limit_wait_s: float = 65.0
    rate_limit_waits: int = 3
    grounding_retries: int = 1
    # Extra tool calls allowed after a rejected answer, so the model can run the missing query.
    retry_tool_calls: int = 3


@dataclass
class Outcome:
    kind: str  # answer | clarification | cannot_answer | error
    answer: str
    query_ids: list[int]
    chart_ids: list[int]
    grounding: dict[str, Any] | None
    stopped: str | None = None  # which limit ended the loop, if any
    usage: dict[str, Any] = field(default_factory=dict)


Event = dict[str, Any]


def system_prompt(box: ToolBox) -> str:
    schema = json.dumps(box.schema(), ensure_ascii=False, default=str)
    if len(schema) > SCHEMA_IN_PROMPT_CHARS:
        schema = json.dumps(
            {"tables": [{"table": t.table, "rows": t.rows} for t in box.ctx.tables]},
            ensure_ascii=False,
        )
        schema += "\n(The schema is large; call get_schema with a table name or search_columns.)"
    project = {"research_topic": box.ctx.topic} if box.ctx.topic else {}
    return PROMPT.replace(
        "{project}",
        (json.dumps(project, ensure_ascii=False) + "\n\n" if project else "")
        + f"<schema>\n{schema}\n</schema>",
    )


async def run_agent(
    client: LLMClient,
    box: ToolBox,
    question: str,
    history: Sequence[Message] = (),
    *,
    limits: Limits = Limits(),  # noqa: B008
) -> AsyncIterator[Event]:
    """Yield progress events; the last one is {"type": "done", "outcome": Outcome}."""
    started = time.perf_counter()
    await box.prepare(question)
    messages: list[Message] = [
        {"role": "system", "content": system_prompt(box)},
        *list(history)[-HISTORY_MESSAGES:],
        {"role": "user", "content": question},
    ]
    # Numbers the user wrote, or earlier answers stated, may be repeated.
    box.state.numbers += grounding.collect_numbers(question, [m.get("content") for m in history])

    tokens = llm_calls = 0
    cost = Decimal(0)
    tool_calls = 0
    tool_limit = limits.max_tool_calls
    rejections = rate_waits = 0
    stopped: str | None = None

    def usage() -> dict[str, Any]:
        return {
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "tokens": tokens,
            "cost_usd": str(cost),
            "sql_errors": box.state.sql_errors,
            "grounding_retries": rejections,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }

    def finish(kind: str, answer: str, args: dict[str, Any], check: Any) -> Event:
        known = set(box.state.query_ids)
        charts = {c["id"] for c in box.state.charts}
        return {
            "type": "done",
            "outcome": Outcome(
                kind=kind,
                answer=answer,
                query_ids=[q for q in _ints(args.get("query_ids")) if q in known]
                or box.state.query_ids,
                chart_ids=[c for c in _ints(args.get("chart_ids")) if c in charts]
                or sorted(charts),
                grounding=check.to_json() if check else None,
                stopped=stopped,
                usage=usage(),
            ),
        }

    while True:
        if stopped is None:
            elapsed = time.perf_counter() - started
            if tool_calls >= tool_limit:
                stopped = "tool_calls"
            elif box.state.sql_errors >= limits.max_sql_errors:
                stopped = "sql_errors"
            elif tokens >= limits.token_budget:
                stopped = "tokens"
            elif elapsed >= limits.time_budget_s:
                stopped = "time"
            if stopped:
                messages.append({"role": "user", "content": _LIMIT_NOTES[stopped]})
        final_turn = stopped is not None

        yield {"type": "status", "text": "Writing the answer" if final_turn else "Thinking"}
        try:
            result = await client.complete(
                messages,
                step="chat_agent",
                prompt_version=PROMPT_VERSION,
                project_id=box.ctx.project_id,
                tools=FINAL_ONLY if final_turn else TOOL_SPECS,
                tool_choice="required",
            )
        except RateLimitError as exc:
            wait = retry_after(exc)
            if (
                wait is not None
                and wait <= limits.rate_limit_wait_s
                and rate_waits < (limits.rate_limit_waits)
            ):
                rate_waits += 1
                yield {"type": "status", "text": f"Waiting {wait:.0f} s for the AI rate limit"}
                await asyncio.sleep(wait + 1)
                continue
            yield finish("error", _rate_limited(wait), {}, None)
            return
        except Exception as exc:
            yield finish(
                "error",
                f"The AI service failed: {type(exc).__name__}. Please try again in a minute.",
                {},
                None,
            )
            return
        llm_calls += 1
        tokens += result.input_tokens + result.output_tokens
        cost += result.cost_usd

        if not result.tool_calls:
            # The model replied in plain text. Accept it as the answer, still checked.
            text = result.text.strip() or "I could not produce an answer."
            yield finish("answer", text, {}, grounding.check(text, box.state.numbers))
            return

        messages.append(result.message or {"role": "assistant", "content": result.text})
        final: tuple[ToolCall, dict[str, Any]] | None = None
        for call in result.tool_calls:
            args = _parse_args(call)
            if call.name == "final_answer" and args is not None:
                final = (call, args)
                continue
            if args is None:
                out: dict[str, Any] = {"error": "Arguments were not valid JSON."}
            elif final_turn:
                out = {"error": "Limit reached; only final_answer is available."}
            else:
                yield {"type": "status", "text": _STATUS.get(call.name, "Working")}
                out = await box.call(call.name, args)
                tool_calls += 1
                yield {"type": "step", "step": box.state.steps[-1].to_json()}
            messages.append(_tool_message(call, out))

        if final is None:
            if final_turn:
                yield finish(
                    "error", "I could not finish within the limits for one question.", {}, None
                )
                return
            continue

        call, args = final
        answer = str(args.get("answer") or "").strip()
        kind = str(args.get("kind") or "answer")
        if kind not in ("answer", "clarification", "cannot_answer"):
            kind = "answer"
        check = grounding.check(answer, box.state.numbers)
        if check.ok or rejections >= limits.grounding_retries or not answer:
            yield finish(kind, answer or "No answer was given.", args, check)
            return

        rejections += 1
        yield {"type": "status", "text": "Checking numbers against the queries"}
        messages.append(
            _tool_message(
                call,
                {
                    "error": "Answer rejected: these numbers do not appear in any tool result: "
                    + ", ".join(check.unsupported)
                    + ". Compute them with run_sql, or remove them, then call final_answer again."
                },
            )
        )
        # Allow a few more calls to compute the missing numbers, even past the limit.
        tool_limit = max(tool_limit, tool_calls + limits.retry_tool_calls)
        if stopped == "tool_calls":
            stopped = None


_STATUS = {
    "get_schema": "Reading the schema",
    "get_column_profile": "Reading a column profile",
    "search_columns": "Searching columns",
    "run_sql": "Running a query",
    "run_stat_test": "Running a statistical test",
    "make_chart": "Making a chart",
}

_LIMIT_NOTES = {
    "tool_calls": "You have used all tool calls for this question.",
    "sql_errors": "Three queries have failed.",
    "tokens": "The token budget for this question is used up.",
    "time": "The time limit for this question has been reached.",
}
_LIMIT_NOTES = {
    k: v + " Call final_answer now with what you have found, and say what is unfinished."
    for k, v in _LIMIT_NOTES.items()
}


def retry_after(exc: Exception) -> float | None:
    """Seconds the provider asks us to wait, if it says (Gemini: "Please retry in 24.4s")."""
    m = RETRY_IN.search(str(exc))  # "retry in 14h39m30s" (a daily limit) does not match
    if m is None:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2))


def _rate_limited(wait: float | None) -> str:
    if wait is None:
        return (
            "The AI service's usage limit has been reached (it may be a daily limit). "
            "Please try again later."
        )
    return f"The AI service is busy (rate limit). Please try again in {wait:.0f} seconds."


def _parse_args(call: ToolCall) -> dict[str, Any] | None:
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return None
    return args if isinstance(args, dict) else None


def _tool_message(call: ToolCall, content: dict[str, Any]) -> Message:
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(content, ensure_ascii=False, default=str),
    }


def _ints(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    out: list[int] = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out
