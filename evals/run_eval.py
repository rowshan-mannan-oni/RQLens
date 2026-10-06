"""Run the evaluation suites.

    python evals/run_eval.py qa --check-gold     # run every gold query; write the gold file
    python evals/run_eval.py qa --llm oracle     # harness self-test, no API key needed
    python evals/run_eval.py qa                  # the real agent (LLM_* settings from .env)
    python evals/run_eval.py qa --smoke          # 15-question smoke set
    python evals/run_eval.py qa --ids cps-01 cps-02

Run from the repository root with PYTHONPATH=apps:. (the Makefile-free way: see README).
Reports go to evals/reports/.
"""

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from api.agent.loop import PROMPT_VERSION, AgentAnswer, Limits, run_agent
from api.agent.tools import AgentConfig, SqlRun, ToolContext
from api.llm.client import LLMClient
from api.llm.tracing import null_tracer
from api.sql.executor import ROW_LIMIT, run_query
from api.stats.tests import run_test
from evals import local_project
from evals.oracle import OracleClient
from evals.scoring import results_match, stat_results_match

EVALS = Path(__file__).parent
QA_FILE = EVALS / "qa" / "questions.v1.jsonl"
GOLD_FILE = EVALS / "qa" / "gold.v1.json"
REPORTS = EVALS / "reports"
GOLD_PREVIEW_ROWS = 20

# A spread of categories for the per-pull-request smoke run.
SMOKE_IDS = [
    "penguins-01", "penguins-04", "penguins-05", "titanic-01", "titanic-04", "taxis-01",
    "taxis-02", "flights-01", "mpg-01", "cps-01", "ames-01", "ant-01", "join-01",
    "ambiguous-01", "unanswerable-01",
]  # fmt: skip


def load_cases(ids: list[str] | None = None, smoke: bool = False) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in QA_FILE.read_text().splitlines() if line.strip()]
    wanted = set(ids or []) | (set(SMOKE_IDS) if smoke else set())
    return [c for c in cases if c["id"] in wanted] if wanted else cases


def gold_result(db: Path, case: dict[str, Any], tables: list[str]) -> dict[str, Any]:
    r = run_query(db, case["gold_sql"], tables, row_limit=ROW_LIMIT)
    if r.error:
        raise RuntimeError(f"{case['id']}: gold SQL failed: {r.error}")
    out: dict[str, Any] = {"columns": r.columns, "rows": r.rows, "row_count": r.row_count}
    if case.get("stat_test"):
        stat_rows = run_query(db, case["gold_sql"], tables, row_limit=200_000).rows
        out["stat"] = run_test(case["stat_test"], stat_rows)
    return out


def check_gold(db: Path, cases: list[dict[str, Any]]) -> None:
    """Run every gold query and write the results for review by hand."""
    gold: dict[str, Any] = {}
    for case in cases:
        if not case["gold_sql"]:
            gold[case["id"]] = {"expected": case["expected"]}
            print(f"{case['id']:18} expects {case['expected']}")
            continue
        g = gold_result(db, case, case["tables"])
        preview = {**g, "rows": g["rows"][:GOLD_PREVIEW_ROWS]}
        gold[case["id"]] = preview
        shown = g["stat"] if "stat" in g else g["rows"][:3]
        print(f"{case['id']:18} {g['row_count']:>4} rows  {json.dumps(shown, default=str)[:110]}")
    GOLD_FILE.write_text(json.dumps(gold, indent=1, default=str) + "\n")
    print(f"\nWrote {GOLD_FILE.relative_to(EVALS.parent)}. Check each result by hand.")


async def run_case(
    client: Any, db: Path, catalog: Any, case: dict[str, Any], config: AgentConfig, model: Any
) -> dict[str, Any]:
    tables = case["tables"]

    async def run_sql(sql: str, row_limit: int) -> SqlRun:
        return SqlRun(
            None, await asyncio.to_thread(run_query, db, sql, tables, row_limit=row_limit)
        )

    ctx = ToolContext(catalog=local_project.subset(catalog, tables), run_sql=run_sql, config=config)
    if isinstance(client, OracleClient):
        client.case = case
    answer: AgentAnswer | None = None
    async for event in run_agent(client, ctx, case["question"], model=model):
        if event.answer is not None:
            answer = event.answer
    assert answer is not None

    passed, reason = score(db, case, answer, ctx)
    return {
        "id": case["id"],
        "category": case["category"],
        "expected": case["expected"],
        "kind": answer.kind,
        "passed": passed,
        "reason": reason,
        "grounded": answer.grounding.get("grounded"),
        "unsupported_numbers": answer.grounding.get("unsupported"),
        "tool_calls": answer.usage.tool_calls,
        "llm_calls": answer.usage.llm_calls,
        "sql_errors": answer.sql_errors,
        "input_tokens": answer.usage.input_tokens,
        "output_tokens": answer.usage.output_tokens,
        "cost_usd": str(answer.usage.cost_usd),
        "latency_ms": answer.latency_ms,
        "stop_reason": answer.stop_reason,
        "answer": answer.text,
        "sql": [ctx.queries[q].sql for q in answer.query_ids if q in ctx.queries],
    }


def score(
    db: Path, case: dict[str, Any], answer: AgentAnswer, ctx: ToolContext
) -> tuple[bool, str]:
    if case["expected"] != "answer":
        ok = answer.kind == case["expected"]
        return ok, "" if ok else f"expected {case['expected']}, got {answer.kind}"
    if answer.kind != "answer":
        return False, f"expected an answer, got {answer.kind}"

    gold = gold_result(db, case, case["tables"])
    if case.get("stat_test"):
        tests = [o for o in ctx.outputs if isinstance(o, dict) and "p_value" in o]
        if any(stat_results_match(t, gold["stat"]) for t in tests):
            return True, ""
        return False, "no matching statistical test" if tests else "no statistical test run"

    cited = [ctx.queries[q] for q in answer.query_ids if q in ctx.queries]
    for r in cited:
        if not r.error and results_match(r.rows, gold["rows"], order_matters=case["order_matters"]):
            return True, ""
    others = [ctx.queries[q] for q in ctx.query_order if q not in answer.query_ids]
    if any(
        not r.error and results_match(r.rows, gold["rows"], order_matters=case["order_matters"])
        for r in others
    ):
        return False, "a matching query ran but was not cited in the answer"
    return False, "no cited query matches the gold result"


def summarise(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    def pct(xs: list[bool]) -> str:
        return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "-"

    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["passed"])
    answered = [r for r in results if r["kind"] == "answer"]
    lines = [
        f"# QA eval {meta['started']}",
        "",
        f"LLM: `{meta['llm']}` · model: `{meta['model']}` · prompt: `{PROMPT_VERSION}` · "
        f"git: `{meta['git_sha']}` · questions: `{QA_FILE.name}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Execution accuracy | {pct([r['passed'] for r in results])} |",
        f"| Grounded answers | {pct([bool(r['grounded']) for r in answered])} |",
        f"| Mean tool calls | {sum(r['tool_calls'] for r in results) / len(results):.1f} |",
        f"| SQL errors (retries) | {sum(r['sql_errors'] for r in results)} |",
        f"| Total cost (USD) | {sum(Decimal(r['cost_usd']) for r in results):.4f} |",
        f"| Mean latency | {sum(r['latency_ms'] for r in results) / len(results) / 1000:.1f} s |",
        "",
        "| Category | Accuracy |",
        "|---|---|",
        *[f"| {c} | {pct(v)} |" for c, v in sorted(by_cat.items())],
        "",
        "## Failures",
        "",
        *[f"- **{r['id']}** ({r['category']}): {r['reason']}" for r in results if not r["passed"]],
    ]
    return "\n".join(lines) + "\n"


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("suite", choices=["qa"])
    parser.add_argument("--check-gold", action="store_true")
    parser.add_argument("--llm", choices=["settings", "oracle"], default="settings")
    parser.add_argument("--model", default=None)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--no-profile", action="store_true", help="experiment 1")
    parser.add_argument("--no-descriptions", action="store_true", help="experiment 2")
    parser.add_argument("--no-retry", action="store_true", help="experiment 3")
    args = parser.parse_args()

    cases = load_cases(args.ids, args.smoke)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "eval.duckdb"
        names = sorted({t for c in cases for t in c["tables"]})
        print(f"Loading {len(names)} datasets…", file=sys.stderr)
        catalog = local_project.build(db, names)
        if args.check_gold:
            check_gold(db, cases)
            return 0

        client: Any = (
            OracleClient() if args.llm == "oracle" else LLMClient.from_settings(tracer=null_tracer)
        )
        config = AgentConfig(
            include_profile=not args.no_profile,
            include_descriptions=not args.no_descriptions,
            self_correction=not args.no_retry,
        )
        meta = {
            "started": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "llm": args.llm,
            "model": args.model or getattr(client, "model", "?"),
            "git_sha": git_sha(),
            "config": vars(config),
            "limits": vars(Limits()),
        }
        results = []
        for case in cases:
            t0 = time.perf_counter()
            r = await run_case(client, db, catalog, case, config, args.model)
            results.append(r)
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"{mark} {case['id']:18} {time.perf_counter() - t0:5.1f}s {r['reason']}")

    REPORTS.mkdir(exist_ok=True)
    stem = f"qa-{datetime.now(UTC):%Y%m%d-%H%M%S}-{args.llm}"
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=1, default=str) + "\n"
    )
    summary = summarise(results, meta)
    (REPORTS / f"{stem}.md").write_text(summary)
    print("\n" + summary)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
