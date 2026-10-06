"""Benchmark C: research-question verdicts against hand labels.

Two modes:
- gold mapping: use each case's labelled parse and mapping; no LLM. Tests the measurements and
  verdict rules end to end on real data. The explanation falls back to the rule messages.
- full: the LLM parses and maps the question, as in the app. Also scores the mapping against
  the labelled one.

Mapping precision and recall compare the set of (role, table.column) pairs of the first
candidate of each construct; a derived expression counts as its text.
"""

import json
from collections import Counter
from itertools import count
from pathlib import Path
from typing import Any

from api.agent.tools import ProjectContext
from api.rq.pipeline import Assessment, assess
from api.rq.schemas import Mapping, ParsedRQ
from api.sql.executor import QueryResult, run_query
from evals import local_project

CASES = Path(__file__).parent / "rq_fit" / "cases.v1.jsonl"
VERDICTS = ("answerable", "partial", "not_answerable")


class NoLLM:
    """Stands in for the client in gold-mapping mode; explaining falls back to the rules."""

    model = "none"

    async def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no LLM in gold-mapping mode")


def load_cases(ids: list[str] | None = None) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    return [c for c in cases if not ids or c["id"] in ids]


def pairs(mapping: Mapping) -> set[tuple[str, str]]:
    out = set()
    for c in mapping.constructs:
        if c.status == "rejected" or not c.candidates:
            continue
        cand = c.candidates[0]
        target = cand.expression if cand.match == "derivable" else f"{cand.table}.{cand.column}"
        out.add((c.role, str(target).lower()))
    return out


async def run_case(
    client: Any, db: Path, ctx: ProjectContext, case: dict[str, Any], gold_mapping: bool
) -> dict[str, Any]:
    tables = case["tables"]
    ids = count(1)

    async def execute(sql: str, row_limit: int) -> tuple[int, QueryResult]:
        return next(ids), run_query(db, sql, tables, row_limit=row_limit)

    gold_parse = ParsedRQ.model_validate(case["gold_parse"])
    gold_map = Mapping.model_validate(case["gold_mapping"])
    a: Assessment = await assess(
        client,
        local_project.subset(ctx, tables),
        case["question"],
        execute,
        parsed=gold_parse if gold_mapping else None,
        mapping=gold_map if gold_mapping else None,
    )
    predicted, gold = pairs(a.mapping), pairs(gold_map)
    hit = len(predicted & gold)
    return {
        "id": case["id"],
        "expected": case["expected_verdict"],
        "verdict": a.verdict,
        "passed": a.verdict == case["expected_verdict"],
        "rules": [f"{r.level}:{r.rule}" for r in a.rules if r.level != "info"],
        "parsed_type": a.parsed.type,
        "mapping_precision": hit / len(predicted) if predicted else (1.0 if not gold else 0.0),
        "mapping_recall": hit / len(gold) if gold else 1.0,
        "explained_by": a.explained_by,
        "problems": a.problems,
        "notes": case.get("notes", ""),
    }


def summarise(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    n = len(results)
    correct = sum(r["passed"] for r in results)
    confusion = Counter((r["expected"], r["verdict"]) for r in results)
    lines = [
        f"# RQ fit eval {meta['started']}",
        "",
        f"Mode: `{meta['mode']}` · model: `{meta['model']}` · git: `{meta['git_sha']}` · "
        f"cases: `{CASES.name}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Verdict agreement | {100 * correct / n:.0f}% ({correct}/{n}) |",
        f"| Mapping precision | {sum(r['mapping_precision'] for r in results) / n:.2f} |",
        f"| Mapping recall | {sum(r['mapping_recall'] for r in results) / n:.2f} |",
        "",
        "Confusion matrix (rows: label, columns: verdict)",
        "",
        "| label \\ verdict | " + " | ".join(VERDICTS) + " |",
        "|---|" + "---|" * len(VERDICTS),
        *[
            f"| {e} | " + " | ".join(str(confusion[(e, v)]) for v in VERDICTS) + " |"
            for e in VERDICTS
        ],
        "",
        "## Disagreements",
        "",
        *[
            f"- **{r['id']}**: label {r['expected']}, verdict {r['verdict']} "
            f"({', '.join(r['rules']) or 'no rules fired'}). {r['notes']}"
            for r in results
            if not r["passed"]
        ],
    ]
    return "\n".join(lines) + "\n"
