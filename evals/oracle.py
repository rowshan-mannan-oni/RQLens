"""A scripted stand-in for the LLM that answers each case with its gold SQL.

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
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        case = self.case
        if case["expected"] != "answer":
            return _call(
                "final_answer",
                {"kind": case["expected"], "text": "Which column do you mean?", "options": []},
            )
        if not tool_messages:
            if case.get("stat_test"):
                return _call("run_stat_test", {"test": case["stat_test"], "sql": case["gold_sql"]})
            return _call("run_sql", {"sql": case["gold_sql"]})

        last = json.loads(tool_messages[-1]["content"])
        if "rows" in last:
            values = [v for row in last["rows"][:5] for v in row]
            text = "Result: " + ", ".join(str(v) for v in values)
        else:
            text = f"p = {last.get('p_value')}, effect size = {last['effect_size']['value']}"
        return _call(
            "final_answer", {"kind": "answer", "text": text, "query_ids": [last.get("query_id")]}
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
