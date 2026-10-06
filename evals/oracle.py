"""A scripted stand-in for the LLM that answers each case with its gold query.

It checks the harness end to end without an API key: tool calls, the SQL guard and executor,
grounding and scoring. An oracle run should pass every case; anything less is a harness bug.
"""

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from api.llm.client import LLMResult, Message, ToolCall


class OracleClient:
    model = "oracle"

    def __init__(self) -> None:
        self.case: dict[str, Any] = {}

    async def complete(self, messages: Sequence[Message], **kwargs: Any) -> LLMResult[Any]:
        case = self.case
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if case["expected"] != "answer":
            return _call("final_answer", {"kind": case["expected"], "answer": "Which one?"})
        if not tool_messages:
            if case.get("stat_test"):
                return _call("run_stat_test", case["stat_test"])
            return _call("run_sql", {"sql": case["gold_sql"], "purpose": "gold query"})

        results = [json.loads(m["content"]) for m in tool_messages]
        last = next(r for r in reversed(results) if "query_id" in r)
        if "rows" in last:
            text = "Result: " + ", ".join(str(v) for row in last["rows"][:5] for v in row)
        else:
            text = f"p = {last['p_value']}, effect size = {last['effect_size']}"
        return _call(
            "final_answer", {"kind": "answer", "answer": text, "query_ids": [last["query_id"]]}
        )


def _call(name: str, args: dict[str, Any]) -> LLMResult[Any]:
    return LLMResult(
        text="",
        parsed=None,
        model="oracle",
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal(0),
        latency_ms=0,
        tool_calls=(ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(args)),),
    )
