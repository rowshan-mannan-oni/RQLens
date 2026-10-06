"""Chat agent: tools over a real DuckDB file and the loop with a scripted fake LLM."""

import json
from pathlib import Path
from typing import Any

import duckdb
import httpx2
import pytest

from api.agent.loop import Limits, Outcome, retry_after, run_agent
from api.agent.tools import ColumnInfo, ProjectContext, TableInfo, ToolBox
from api.llm.client import LLMClient
from api.llm.tracing import TraceRecord
from api.sql.executor import QueryResult, run_query


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "data.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE survey AS SELECT i AS id, 20 + i % 50 AS age, "
        "CASE WHEN i % 3 = 0 THEN 'M' ELSE 'F' END AS gender, "
        "'person' || i || '@example.com' AS email FROM range(1000) t(i)"
    )
    con.close()
    return path


def column(name: str, kind: str, *, pii: bool = False, **profile: Any) -> ColumnInfo:
    return ColumnInfo(name, name.title(), "BIGINT", kind, None, None, None, pii, profile)


def make_box(db: Path, *, share_samples: bool = True) -> ToolBox:
    ctx = ProjectContext(
        project_id=1,
        topic=None,
        share_samples=share_samples,
        tables=[
            TableInfo(
                "survey",
                "survey.csv",
                1000,
                [
                    column("id", "identifier"),
                    column("age", "numeric", missing_pct=0.0),
                    column(
                        "gender",
                        "categorical",
                        top_values=[{"value": "F", "count": 666, "share": 0.666}],
                    ),
                    column("email", "identifier", pii=True, samples=["a@b.com"]),
                ],
            )
        ],
    )
    next_id = iter(range(1, 1000))

    async def execute(sql: str, row_limit: int) -> tuple[int, QueryResult]:
        return next(next_id), run_query(db, sql, {"survey"}, row_limit=row_limit)

    return ToolBox(ctx, execute)


# ----- tools -----


async def test_run_sql_returns_rows_and_records_numbers(db: Path) -> None:
    box = make_box(db)
    out = await box.call(
        "run_sql",
        {"sql": "SELECT gender, count(*) AS n FROM survey GROUP BY 1 ORDER BY 1", "purpose": "x"},
    )
    assert out["rows"] == [["F", 666], ["M", 334]]
    assert out["query_id"] == 1
    assert 666.0 in box.state.numbers
    assert box.state.steps[0].query_id == 1


async def test_sql_errors_are_returned_and_counted(db: Path) -> None:
    box = make_box(db)
    out = await box.call("run_sql", {"sql": "SELECT nope FROM survey", "purpose": "x"})
    assert "nope" in out["error"]
    out = await box.call("run_sql", {"sql": "DROP TABLE survey", "purpose": "x"})
    assert out["error"] == "Only SELECT queries are allowed."
    assert box.state.sql_errors == 2


async def test_personal_data_is_hidden_from_the_model(db: Path) -> None:
    box = make_box(db)
    out = await box.call("run_sql", {"sql": "SELECT email FROM survey LIMIT 2", "purpose": "x"})
    assert out["rows"] == [["<masked>"], ["<masked>"]]
    # count(*) next to a normal column is not treated as reading personal data
    out = await box.call(
        "run_sql", {"sql": "SELECT gender, count(*) FROM survey GROUP BY 1", "purpose": "x"}
    )
    assert {r[0] for r in out["rows"]} == {"F", "M"}
    # Emails produced by other means are still scrubbed.
    out = await box.call(
        "run_sql", {"sql": "SELECT 'x@y.org' AS contact FROM survey LIMIT 1", "purpose": "x"}
    )
    assert out["rows"] == [["<email>"]]

    profile = await box.call("get_column_profile", {"table": "survey", "column": "email"})
    assert "samples" not in profile["profile"]


async def test_samples_follow_the_project_setting(db: Path) -> None:
    shared = await make_box(db).call("get_column_profile", {"table": "survey", "column": "gender"})
    assert "top_values" in shared["profile"]
    hidden = await make_box(db, share_samples=False).call(
        "get_column_profile", {"table": "survey", "column": "gender"}
    )
    assert "top_values" not in hidden["profile"]


async def test_stat_test_logs_its_query(db: Path) -> None:
    box = make_box(db)
    out = await box.call(
        "run_stat_test",
        {"test": "mann_whitney", "table": "survey", "x": "age", "y": "gender", "where": "age > 0"},
    )
    assert out["test"] == "mann_whitney" and out["n"] == 1000
    assert box.state.query_ids == [1]
    assert box.state.steps[0].result is not None


async def test_stat_test_rejects_unknown_column(db: Path) -> None:
    out = await make_box(db).call(
        "run_stat_test", {"test": "spearman", "table": "survey", "x": "age", "y": "height"}
    )
    assert "height" in out["error"]


async def test_chart_uses_a_query_result(db: Path) -> None:
    box = make_box(db)
    await box.call(
        "run_sql",
        {"sql": "SELECT gender, count(*) AS n FROM survey GROUP BY 1 ORDER BY 1", "purpose": "x"},
    )
    out = await box.call(
        "make_chart", {"query_id": 1, "type": "bar", "x": "gender", "y": ["n"], "title": "t"}
    )
    assert out == {"chart_id": 1, "points": 2}
    assert box.state.charts[0]["data"] == [{"gender": "F", "n": 666}, {"gender": "M", "n": 334}]
    bad = await box.call(
        "make_chart", {"query_id": 1, "type": "bar", "x": "n", "y": ["gender"], "title": "t"}
    )
    assert "not numeric" in bad["error"]


async def test_search_columns(db: Path) -> None:
    out = await make_box(db).call("search_columns", {"query": "gender of respondent"})
    assert out["matches"][0]["name"] == "gender"


# ----- loop -----


def tool_reply(*calls: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for i, (name, args) in enumerate(calls)
        ],
    }


class ScriptedLLM:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.requests: list[Any] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        message = self.replies.pop(0)
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )


def client_for(llm: ScriptedLLM, traces: list[TraceRecord] | None = None) -> LLMClient:
    async def tracer(record: TraceRecord) -> None:
        if traces is not None:
            traces.append(record)

    return LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        tracer=tracer,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(llm)),
    )


async def run(
    llm: ScriptedLLM, box: ToolBox, limits: Limits | None = None
) -> tuple[Outcome, list[dict[str, Any]]]:
    events = [
        e
        async for e in run_agent(client_for(llm), box, "How many women?", limits=limits or Limits())
    ]
    assert events[-1]["type"] == "done"
    return events[-1]["outcome"], events


COUNT_SQL = "SELECT count(*) AS n FROM survey WHERE gender = 'F'"


async def test_answer_after_self_correction(db: Path) -> None:
    llm = ScriptedLLM(
        [
            tool_reply(("run_sql", {"sql": "SELECT count(*) FROM survey WHERE sex = 'F'",
                                    "purpose": "count women"})),
            tool_reply(("run_sql", {"sql": COUNT_SQL, "purpose": "count women"})),
            tool_reply(("final_answer", {"answer": "There are 666 women.", "kind": "answer",
                                         "query_ids": [2]})),
        ]
    )  # fmt: skip
    box = make_box(db)
    outcome, events = await run(llm, box)

    assert outcome.kind == "answer"
    assert outcome.answer == "There are 666 women."
    assert outcome.query_ids == [2]
    assert outcome.grounding == {"ok": True, "checked": 1, "unsupported": []}
    assert outcome.usage["sql_errors"] == 1 and outcome.usage["llm_calls"] == 3
    # The SQL error went back to the model as a tool message.
    tool_messages = [m for m in llm.requests[1]["messages"] if m["role"] == "tool"]
    assert "sex" in tool_messages[0]["content"]
    assert [e["step"]["tool"] for e in events if e["type"] == "step"] == ["run_sql", "run_sql"]


async def test_ungrounded_answer_is_sent_back_once_then_flagged(db: Path) -> None:
    llm = ScriptedLLM(
        [
            tool_reply(("run_sql", {"sql": COUNT_SQL, "purpose": "count"})),
            tool_reply(("final_answer", {"answer": "There are 700 women.", "kind": "answer"})),
            tool_reply(("final_answer", {"answer": "Roughly 700 women.", "kind": "answer"})),
        ]
    )
    outcome, _ = await run(llm, make_box(db))
    assert outcome.grounding == {"ok": False, "checked": 1, "unsupported": ["700"]}
    assert outcome.usage["grounding_retries"] == 1
    rejection = llm.requests[2]["messages"][-1]
    assert rejection["role"] == "tool" and "700" in rejection["content"]


async def test_ungrounded_answer_can_be_fixed(db: Path) -> None:
    llm = ScriptedLLM(
        [
            tool_reply(("final_answer", {"answer": "There are 666 women.", "kind": "answer"})),
            tool_reply(("run_sql", {"sql": COUNT_SQL, "purpose": "count"})),
            tool_reply(("final_answer", {"answer": "There are 666 women.", "kind": "answer"})),
        ]
    )
    outcome, _ = await run(llm, make_box(db))
    assert outcome.grounding is not None and outcome.grounding["ok"]


async def test_clarifying_question(db: Path) -> None:
    llm = ScriptedLLM(
        [
            tool_reply(
                ("final_answer", {"answer": "Average of which column: age or id?",
                                  "kind": "clarification"})
            )
        ]
    )  # fmt: skip
    outcome, _ = await run(llm, make_box(db))
    assert outcome.kind == "clarification"
    assert outcome.query_ids == []


async def test_tool_call_limit_forces_a_final_answer(db: Path) -> None:
    llm = ScriptedLLM(
        [
            tool_reply(("get_schema", {})),
            tool_reply(("get_schema", {})),
            tool_reply(("final_answer", {"answer": "Not finished.", "kind": "answer"})),
        ]
    )
    outcome, _ = await run(llm, make_box(db), Limits(max_tool_calls=2))
    assert outcome.stopped == "tool_calls"
    assert outcome.answer == "Not finished."
    last = llm.requests[2]
    assert [t["function"]["name"] for t in last["tools"]] == ["final_answer"]
    assert "used all tool calls" in last["messages"][-1]["content"]


async def test_three_sql_errors_stop_the_loop(db: Path) -> None:
    bad = ("run_sql", {"sql": "SELECT nope FROM survey", "purpose": "x"})
    llm = ScriptedLLM(
        [
            tool_reply(bad),
            tool_reply(bad),
            tool_reply(bad),
            tool_reply(("final_answer", {"answer": "The query kept failing.", "kind": "answer"})),
        ]
    )
    outcome, _ = await run(llm, make_box(db))
    assert outcome.stopped == "sql_errors"
    assert len(llm.requests) == 4


async def test_failed_llm_call_is_traced_and_reported(db: Path) -> None:
    def failing(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, json={"error": "overloaded"})

    traces: list[TraceRecord] = []

    async def tracer(record: TraceRecord) -> None:
        traces.append(record)

    client = LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        tracer=tracer,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(failing)),
    )
    events = [e async for e in run_agent(client, make_box(db), "q")]
    outcome = events[-1]["outcome"]
    assert outcome.kind == "error"
    assert len(traces) == 1 and "error" in traces[0].response_json


def test_retry_after_reads_short_waits_only() -> None:
    assert retry_after(Exception("Please retry in 24.44s.")) == pytest.approx(24.44)
    assert retry_after(Exception("Please retry in 1m5s.")) == 65
    assert retry_after(Exception("Please retry in 14h39m30.8s.")) is None
    assert retry_after(Exception("quota exceeded")) is None


async def test_waits_out_a_per_minute_rate_limit(db: Path) -> None:
    replies = [
        httpx2.Response(429, json={"error": {"message": "Please retry in 0.01s."}}),
        None,
    ]
    llm = ScriptedLLM([tool_reply(("final_answer", {"answer": "Done.", "kind": "answer"}))])

    def provider(request: httpx2.Request) -> httpx2.Response:
        return replies.pop(0) or llm(request)

    client = LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        tracer=lambda r: _noop(),
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)),
    )
    events = [e async for e in run_agent(client, make_box(db), "q")]
    assert any("rate limit" in e.get("text", "") for e in events)
    assert events[-1]["outcome"].answer == "Done."


async def _noop() -> None:
    return None
