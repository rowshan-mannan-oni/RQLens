"""Run the evaluation suites.

    python evals/run_eval.py qa --check-gold     # run every gold query; write the gold file
    python evals/run_eval.py qa --llm oracle     # harness self-test, no API key needed
    python evals/run_eval.py qa                  # the real agent (LLM_* settings from .env)
    python evals/run_eval.py qa --smoke          # 15-question smoke set
    python evals/run_eval.py qa --ids cps-01 cps-02
    python evals/run_eval.py rq --gold-mapping   # RQ verdicts from labelled mappings, no LLM
    python evals/run_eval.py rq                  # RQ fit with the LLM parsing and mapping
    python evals/run_eval.py lit --llm oracle    # literature extraction, harness self-test
    python evals/run_eval.py lit                 # literature extraction with the real model
    python evals/run_eval.py lit --no-check      # experiment 8: without the citation check
    python evals/run_eval.py lit --retrieval     # experiment 7: retrieved passages per column

Run from the repository root with PYTHONPATH=apps:. so both `api` and `evals` import.
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
from functools import partial
from itertools import count
from pathlib import Path
from typing import Any

from api.agent.loop import PROMPT_VERSION, Limits, Outcome, run_agent
from api.agent.tools import ProjectContext, ToolBox
from api.config import get_settings
from api.llm.client import LLMClient
from api.llm.tracing import null_tracer
from api.semantic.column_retrieval import ColumnRetriever
from api.sql.executor import ROW_LIMIT, QueryResult, run_query
from api.stats.library import run_test
from evals import insights_eval, lit_eval, local_project, rq_eval
from evals.oracle import OracleClient
from evals.scoring import results_match, stat_results_match

EVALS = Path(__file__).parent
QA_FILE = EVALS / "qa" / "questions.v1.jsonl"
GOLD_FILE = EVALS / "qa" / "gold.v1.json"
REPORTS = EVALS / "reports"
GOLD_PREVIEW_ROWS = 20
STAT_ROWS = 100_000

# A spread of categories for the per-pull-request smoke run.
SMOKE_IDS = [
    "penguins-01",
    "penguins-04",
    "penguins-05",
    "titanic-01",
    "titanic-04",
    "taxis-01",
    "taxis-02",
    "flights-01",
    "mpg-01",
    "cps-01",
    "ames-01",
    "ant-01",
    "join-01",
    "ambiguous-01",
    "unanswerable-01",
]


def load_cases(ids: list[str] | None = None, smoke: bool = False) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in QA_FILE.read_text().splitlines() if line.strip()]
    wanted = set(ids or []) | (set(SMOKE_IDS) if smoke else set())
    return [c for c in cases if c["id"] in wanted] if wanted else cases


def gold_result(db: Path, case: dict[str, Any]) -> dict[str, Any]:
    limit = STAT_ROWS if case.get("stat_test") else ROW_LIMIT
    r = run_query(db, case["gold_sql"], case["tables"], row_limit=limit)
    if r.error:
        raise RuntimeError(f"{case['id']}: gold SQL failed: {r.error}")
    out: dict[str, Any] = {"columns": r.columns, "rows": r.rows, "row_count": r.row_count}
    if case.get("stat_test"):
        test = case["stat_test"]["test"]
        out["stat"] = run_test(test, [x for x, _ in r.rows], [y for _, y in r.rows]).to_json()
        out["rows"] = []  # the raw pairs are input to the test, not the answer
    return out


def check_gold(db: Path, cases: list[dict[str, Any]]) -> None:
    """Run every gold query and write the results for review by hand."""
    gold: dict[str, Any] = {}
    for case in cases:
        if not case["gold_sql"]:
            gold[case["id"]] = {"expected": case["expected"]}
            print(f"{case['id']:18} expects {case['expected']}")
            continue
        g = gold_result(db, case)
        gold[case["id"]] = {**g, "rows": g["rows"][:GOLD_PREVIEW_ROWS]}
        shown = g.get("stat") or g["rows"][:3]
        print(f"{case['id']:18} {g['row_count']:>5} rows  {json.dumps(shown, default=str)[:110]}")
    GOLD_FILE.write_text(json.dumps(gold, indent=1, default=str) + "\n")
    print(f"\nWrote {GOLD_FILE.relative_to(EVALS.parent)}. Check each result by hand.")


async def run_case(
    client: Any,
    db: Path,
    ctx: ProjectContext,
    case: dict[str, Any],
    limits: Limits,
    retriever: ColumnRetriever | None = None,
) -> dict[str, Any]:
    tables = case["tables"]
    ids = count(1)

    async def execute(sql: str, row_limit: int) -> tuple[int, QueryResult]:
        r = await asyncio.to_thread(run_query, db, sql, tables, row_limit=row_limit)
        return next(ids), r

    box = ToolBox(local_project.subset(ctx, tables), execute, retriever)
    if isinstance(client, OracleClient):
        client.case = case
    outcome: Outcome | None = None
    async for event in run_agent(client, box, case["question"], limits=limits):
        if event["type"] == "done":
            outcome = event["outcome"]
    assert outcome is not None

    passed, reason = score(db, case, outcome, box)
    usage = outcome.usage
    return {
        "id": case["id"],
        "category": case["category"],
        "expected": case["expected"],
        "kind": outcome.kind,
        "passed": passed,
        "reason": reason,
        "grounded": bool(outcome.grounding and outcome.grounding["ok"]),
        "unsupported_numbers": (outcome.grounding or {}).get("unsupported", []),
        "stopped": outcome.stopped,
        **usage,
        "answer": outcome.answer,
        "sql": [box.state.results[q].sql for q in outcome.query_ids if q in box.state.results],
    }


def score(db: Path, case: dict[str, Any], outcome: Outcome, box: ToolBox) -> tuple[bool, str]:
    if case["expected"] != "answer":
        ok = outcome.kind == case["expected"]
        return ok, "" if ok else f"expected {case['expected']}, got {outcome.kind}"
    if outcome.kind != "answer":
        return False, f"expected an answer, got {outcome.kind}"

    gold = gold_result(db, case)
    if case.get("stat_test"):
        tests = [s.result for s in box.state.steps if s.tool == "run_stat_test" and s.result]
        if any(stat_results_match(t, gold["stat"]) for t in tests):
            return True, ""
        return False, "no matching statistical test" if tests else "no statistical test run"

    def matches(query_id: int) -> bool:
        r = box.state.results[query_id]
        return not r.error and results_match(
            r.rows, gold["rows"], order_matters=case["order_matters"]
        )

    if any(matches(q) for q in outcome.query_ids if q in box.state.results):
        return True, ""
    if any(matches(q) for q in box.state.query_ids if q not in outcome.query_ids):
        return False, "a matching query ran but the answer did not cite it"
    return False, "no cited query matches the gold result"


def summarise(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    def pct(xs: list[bool]) -> str:
        return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "-"

    by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["passed"])
    answered = [r for r in results if r["kind"] == "answer"]
    n = len(results)
    lines = [
        f"# QA eval {meta['started']}",
        "",
        f"LLM: `{meta['llm']}` · model: `{meta['model']}` · prompt: `{PROMPT_VERSION}` · "
        f"git: `{meta['git_sha']}` · questions: `{QA_FILE.name}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Execution accuracy | {pct([r['passed'] for r in results])} |",
        f"| Grounded answers | {pct([r['grounded'] for r in answered])} |",
        f"| Mean tool calls | {sum(r['tool_calls'] for r in results) / n:.1f} |",
        f"| Failed queries | {sum(r['sql_errors'] for r in results)} |",
        f"| Grounding retries | {sum(r['grounding_retries'] for r in results)} |",
        f"| Total cost (USD) | {sum(Decimal(r['cost_usd']) for r in results):.4f} |",
        f"| Mean latency | {sum(r['duration_ms'] for r in results) / n / 1000:.1f} s |",
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
    parser.add_argument("suite", choices=["qa", "rq", "insights", "lit"])
    parser.add_argument("--check-gold", action="store_true")
    parser.add_argument("--llm", choices=["settings", "oracle"], default="settings")
    parser.add_argument("--model", default=None, help="override LLM_MODEL")
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--no-retrieval", action="store_true", help="word matching only (experiment 6)"
    )
    parser.add_argument(
        "--gold-mapping", action="store_true", help="rq: use labelled mappings, no LLM"
    )
    parser.add_argument(
        "--no-check", action="store_true", help="lit: no citation check or retry (experiment 8)"
    )
    parser.add_argument(
        "--retrieval", action="store_true", help="lit: retrieved passages only (experiment 7)"
    )
    args = parser.parse_args()
    if args.suite == "lit":
        return await main_lit(args)
    if args.suite == "rq":
        return await main_rq(args)
    if args.suite == "insights":
        return await main_insights(args)

    cases = load_cases(args.ids, args.smoke)
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "eval.duckdb"
        names = sorted({t for c in cases for t in c["tables"]})
        print(f"Loading {len(names)} datasets…", file=sys.stderr)
        ctx = local_project.build(db, names)
        if args.check_gold:
            check_gold(db, cases)
            return 0

        client: Any
        retriever = None
        if args.llm == "oracle":
            client = OracleClient()
        else:
            client = LLMClient.from_settings(tracer=null_tracer)
            if args.model:
                client.model = args.model
            if client.embedding_model and not args.no_retrieval:
                retriever = ColumnRetriever(partial(client.embed, step="column_retrieval"))
        limits = Limits()
        meta = {
            "started": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "llm": args.llm,
            "model": client.model,
            "git_sha": git_sha(),
            "limits": vars(limits),
            "retrieval": "embeddings" if retriever else "words",
        }
        results = []
        for case in cases:
            t0 = time.perf_counter()
            r = await run_case(client, db, ctx, case, limits, retriever)
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


async def main_rq(args: argparse.Namespace) -> int:
    cases = rq_eval.load_cases(args.ids)
    client: Any = rq_eval.NoLLM() if args.gold_mapping else LLMClient.from_settings(null_tracer)
    if args.model and not args.gold_mapping:
        client.model = args.model
    meta = {
        "started": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": "gold-mapping" if args.gold_mapping else "full",
        "model": client.model,
        "git_sha": git_sha(),
    }
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "eval.duckdb"
        ctx = local_project.build(db, sorted({t for c in cases for t in c["tables"]}))
        results = []
        for case in cases:
            r = await rq_eval.run_case(client, db, ctx, case, args.gold_mapping)
            results.append(r)
            mark = "AGREE   " if r["passed"] else "DISAGREE"
            print(f"{mark} {case['id']:26} {r['verdict']:15} {', '.join(r['rules'])}")

    REPORTS.mkdir(exist_ok=True)
    stem = f"rq-{datetime.now(UTC):%Y%m%d-%H%M%S}-{meta['mode']}"
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=1, default=str) + "\n"
    )
    summary = rq_eval.summarise(results, meta)
    (REPORTS / f"{stem}.md").write_text(summary)
    print("\n" + summary)
    return 0


async def main_insights(args: argparse.Namespace) -> int:
    client = None if args.llm == "oracle" else LLMClient.from_settings(null_tracer)
    if client is not None and not get_settings().llm_api_key:
        client = None  # no key: rules-only planning and template statements
    meta = {
        "started": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "llm": "none" if client is None else client.model,
        "git_sha": git_sha(),
    }
    names = args.ids or [e["name"] for e in local_project.manifest()]
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            r = await insights_eval.run_dataset(name, Path(tmp), client)
            results.append(r)
            print(
                f"{name:14} {r['insights']:>2} insights, {r['findings']:>2} findings, "
                f"{len(r['ungrounded'])} ungrounded, {len(r['failed'])} failed"
            )
    REPORTS.mkdir(exist_ok=True)
    stem = f"insights-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    (REPORTS / f"{stem}.json").write_text(insights_eval.report_json(results, meta))
    summary = insights_eval.summarise(results, meta)
    (REPORTS / f"{stem}.md").write_text(summary)
    print("\n" + summary)
    return 0 if all(not r["ungrounded"] for r in results) else 1


async def main_lit(args: argparse.Namespace) -> int:
    labels = lit_eval.load_labels()
    client: Any
    if args.llm == "oracle":
        client = lit_eval.LitOracle(labels)
    else:
        client = LLMClient.from_settings(tracer=null_tracer)
        if args.model:
            client.model = args.model
    meta = {
        "started": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": client.model,
        "check": not args.no_check,
        "passages": "retrieved per column" if args.retrieval else "whole paper",
        "git_sha": git_sha(),
    }
    results = []
    for paper_id, spec in lit_eval.corpus(args.ids):
        r = await lit_eval.run_paper(
            client, paper_id, spec, labels.get(paper_id, {}),
            check=not args.no_check, retrieval=args.retrieval,
        )  # fmt: skip
        results.append(r)
        ok = sum(1 for c in r["cells"] if c.get("correct") or c.get("not_found_correct"))
        print(f"{paper_id:20} {ok:>2}/{len(r['cells'])} cells right  {r['seconds']:5.1f}s")
    REPORTS.mkdir(exist_ok=True)
    stem = f"lit-{datetime.now(UTC):%Y%m%d-%H%M%S}-{args.llm}"
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=1, default=str) + "\n"
    )
    summary = lit_eval.summarise(results, meta)
    (REPORTS / f"{stem}.md").write_text(summary)
    print("\n" + summary)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
