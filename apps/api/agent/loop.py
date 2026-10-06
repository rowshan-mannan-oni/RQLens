"""The chat agent: a bounded tool loop that answers one question about a project's data.

Each step asks the model for tool calls, runs them and feeds the results back, until the model
calls final_answer or a limit is reached. Before an answer is accepted, the grounding check
confirms every number in it appeared in a tool result; if not, the model gets one chance to fix
the answer, after which it is flagged.

Progress is yielded as events so the API can stream it to the browser.
"""

import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from api.agent import grounding
from api.agent.tools import (
    TOOL_SPECS,
    ToolContext,
    call_tool,
    schema_context,
    tool_specs,
)
from api.llm.client import LLMClient, LLMResult, ToolCall

PROMPT_VERSION = "chat_agent.v1"
PROMPT = (Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)
FINAL_ANSWER_SPEC = next(t for t in TOOL_SPECS if t["function"]["name"] == "final_answer")
HISTORY_MESSAGES = 6
HISTORY_CHARS = 2_000

AnswerKind = Literal["answer", "clarification", "cannot_answer", "error"]


@dataclass
class Limits:
    max_tool_calls: int = 15
    max_tokens: int = 200_000  # input plus output, summed over all model calls
    max_seconds: float = 120.0


@dataclass
class Usage:
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)

    def add(self, result: LLMResult[Any]) -> None:
        self.llm_calls += 1
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.cost_usd += result.cost_usd


@dataclass
class AgentAnswer:
    kind: AnswerKind
    text: str
    query_ids: list[int]
    chart: dict[str, Any] | None
    options: list[str]
    grounding: dict[str, Any]
    flagged: bool  # numbers in the answer could not be traced to a tool result
    stop_reason: str
    usage: Usage
    latency_ms: int
    sql_errors: int
    steps: list[dict[str, Any]] = field(default_factory=list)

    def details(self) -> dict[str, Any]:
        """JSON stored with the assistant message."""
        return {
            "kind": self.kind,
            "query_ids": self.query_ids,
            "options": self.options,
            "grounding": self.grounding,
            "flagged": self.flagged,
            "stop_reason": self.stop_reason,
            "steps": self.steps,
            "sql_errors": self.sql_errors,
            "prompt_version": PROMPT_VERSION,
            "usage": {
                "llm_calls": self.usage.llm_calls,
                "tool_calls": self.usage.tool_calls,
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cost_usd": str(self.usage.cost_usd),
                "latency_ms": self.latency_ms,
            },
        }


@dataclass
class AgentEvent:
    type: Literal["step", "answer"]
    data: dict[str, Any]
    answer: AgentAnswer | None = None


def build_messages(
    ctx: ToolContext, question: str, history: Sequence[dict[str, str]]
) -> list[dict[str, Any]]:
    schema = {"research_topic": ctx.catalog.topic, **schema_context(ctx.catalog, ctx.config)}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PROMPT},
        {
            "role": "system",
            "content": "<schema>\n"
            + json.dumps(schema, ensure_ascii=False, default=str)
            + "\n</schema>",
        },
    ]
    for m in history[-HISTORY_MESSAGES:]:
        content = m["content"][:HISTORY_CHARS]
        if m["role"] == "user":
            content = f"<question>\n{content}\n</question>"
        messages.append({"role": m["role"], "content": content})
    messages.append({"role": "user", "content": f"<question>\n{question}\n</question>"})
    return messages


async def run_agent(
    client: LLMClient,
    ctx: ToolContext,
    question: str,
    *,
    history: Sequence[dict[str, str]] = (),
    limits: Limits | None = None,
    project_id: int | None = None,
    eval_run_id: int | None = None,
    model: str | None = None,
) -> AsyncIterator[AgentEvent]:
    limits = limits or Limits()
    started = time.perf_counter()
    usage = Usage()
    steps: list[dict[str, Any]] = []
    messages = build_messages(ctx, question, history)
    tools = tool_specs(ctx.config)
    regrounded = False
    sql_errors = 0

    def elapsed_ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    def finish(
        kind: AnswerKind,
        text: str,
        stop_reason: str,
        *,
        query_ids: Sequence[int] = (),
        chart_id: int | None = None,
        options: Sequence[str] = (),
        check: grounding.GroundingResult | None = None,
    ) -> AgentEvent:
        known = [q for q in query_ids if q in ctx.queries]
        if not known:
            # Every answer shows its queries: default to all successful ones.
            known = [q for q in ctx.query_order if not ctx.queries[q].error]
        chart = next((c for c in ctx.charts if c["chart_id"] == chart_id), None)
        if chart is None and kind == "answer" and len(ctx.charts) == 1:
            chart = ctx.charts[0]
        check = check or grounding.check(text, ctx.outputs, question=question, sql=_sql_texts(ctx))
        answer = AgentAnswer(
            kind=kind,
            text=text,
            query_ids=list(dict.fromkeys(known)),
            chart=chart,
            options=[str(o) for o in options][:6],
            grounding=check.summary(),
            flagged=not check.grounded and kind != "error",
            stop_reason=stop_reason,
            usage=usage,
            latency_ms=elapsed_ms(),
            sql_errors=sql_errors,
            steps=steps,
        )
        return AgentEvent("answer", {"kind": kind}, answer)

    async def model_call(only_final: bool = False) -> LLMResult[Any]:
        result = await client.complete(
            messages,
            step="chat_agent",
            prompt_version=PROMPT_VERSION,
            project_id=project_id,
            eval_run_id=eval_run_id,
            model=model,
            tools=[FINAL_ANSWER_SPEC] if only_final else tools,
            tool_choice="required" if only_final else "auto",
        )
        usage.add(result)
        messages.append(result.assistant_message())
        return result

    stop_reason = ""
    while True:
        if usage.tool_calls >= limits.max_tool_calls:
            stop_reason = "limit_tool_calls"
        elif usage.input_tokens + usage.output_tokens >= limits.max_tokens:
            stop_reason = "limit_tokens"
        elif time.perf_counter() - started >= limits.max_seconds:
            stop_reason = "limit_time"
        if stop_reason:
            break

        try:
            result = await model_call()
        except Exception as exc:
            yield finish("error", f"The AI model could not be reached: {exc}", "llm_error")
            return

        if not result.tool_calls:
            # A plain text reply ends the turn.
            yield finish("answer", result.text.strip() or "(no answer)", "text_reply")
            return

        final: ToolCall | None = None
        for call in result.tool_calls:
            if call.name == "final_answer" and final is None:
                final = call
                continue
            args = _parse_args(call)
            usage.tool_calls += 1
            if args is None:
                output: Any = {"error": "The arguments were not valid JSON."}
            else:
                output = await call_tool(ctx, call.name, args)
            if isinstance(output, dict) and output.get("error") and call.name == "run_sql":
                sql_errors += 1
            step = _step_summary(call.name, args or {}, output)
            steps.append(step)
            yield AgentEvent("step", step)
            messages.append(_tool_message(call.id, output))

        if final is None:
            continue

        args = _parse_args(final) or {}
        kind: AnswerKind = "answer"
        if args.get("kind") in ("clarification", "cannot_answer"):
            kind = args["kind"]
        text = str(args.get("text") or "").strip()
        query_ids = [int(q) for q in args.get("query_ids") or [] if isinstance(q, int | float)]
        chart_id = args.get("chart_id") if isinstance(args.get("chart_id"), int) else None
        raw_options = args.get("options")
        options = [str(o) for o in raw_options] if isinstance(raw_options, list) else []

        check = grounding.check(text, ctx.outputs, question=question, sql=_sql_texts(ctx))
        if not text:
            messages.append(_tool_message(final.id, {"error": "text is empty."}))
            continue
        if not check.grounded and not regrounded:
            regrounded = True
            steps.append({"tool": "grounding_check", "unsupported": check.unsupported})
            yield AgentEvent("step", steps[-1])
            messages.append(
                _tool_message(
                    final.id,
                    {
                        "error": "These numbers in your answer do not appear in any tool "
                        f"result: {', '.join(check.unsupported)}. Compute them with run_sql, "
                        "or remove them, then call final_answer again."
                    },
                )
            )
            continue
        messages.append(_tool_message(final.id, {"ok": True}))
        yield finish(
            kind,
            text,
            "final_answer",
            query_ids=query_ids,
            chart_id=chart_id,
            options=options,
            check=check,
        )
        return

    # A limit was reached: ask for an answer with what is known so far.
    messages.append(
        {
            "role": "user",
            "content": f"The {stop_reason.removeprefix('limit_').replace('_', ' ')} limit for "
            "this question is reached. Call final_answer now using only the results you have, "
            "and say what remains unanswered.",
        }
    )
    try:
        result = await model_call(only_final=True)
    except Exception as exc:
        yield finish("error", f"The AI model could not be reached: {exc}", "llm_error")
        return
    final = next((c for c in result.tool_calls if c.name == "final_answer"), None)
    args = (_parse_args(final) if final else None) or {}
    text = str(args.get("text") or result.text or "").strip()
    if not text:
        text = "I could not finish this question within the limits. Try a narrower question."
    yield finish(
        "answer",
        text,
        stop_reason,
        query_ids=[int(q) for q in args.get("query_ids") or [] if isinstance(q, int | float)],
        check=grounding.check(text, ctx.outputs, question=question, sql=_sql_texts(ctx)),
    )


def _parse_args(call: ToolCall) -> dict[str, Any] | None:
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return None
    return args if isinstance(args, dict) else None


def _tool_message(call_id: str, output: Any) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(output, ensure_ascii=False, default=str),
    }


def _sql_texts(ctx: ToolContext) -> list[str]:
    return [r.sql for r in ctx.queries.values()]


def _step_summary(name: str, args: dict[str, Any], output: Any) -> dict[str, Any]:
    """A short record of one tool call for the UI and the stored message."""
    step: dict[str, Any] = {"tool": name}
    out = output if isinstance(output, dict) else {}
    if name in ("run_sql", "run_stat_test"):
        step["query_id"] = out.get("query_id")
        if name == "run_stat_test":
            step["test"] = args.get("test")
            if "p_value" in out:
                step["p_value"] = out["p_value"]
                step["effect_size"] = out.get("effect_size")
                step["n"] = out.get("n")
        elif "row_count" in out:
            step["row_count"] = out["row_count"]
    elif name in ("get_column_profile",):
        step["column"] = f"{args.get('table')}.{args.get('column')}"
    elif name == "search_columns":
        step["query"] = args.get("query")
    elif name == "make_chart":
        step["chart_id"] = out.get("chart_id")
    if out.get("error"):
        step["error"] = out["error"]
    return step
