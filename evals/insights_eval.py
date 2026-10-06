"""Phase 4 check: generate insights for every development dataset, each as its own project,
and confirm no card carries an untraceable number. Research questions come from the labelled
RQ cases for that dataset, so data-quality insights and RQ ranking are exercised too.
"""

import json
from itertools import count
from pathlib import Path
from typing import Any

from api.insights.pipeline import Question, generate
from api.rq.schemas import Mapping
from api.sql.executor import QueryResult, run_query
from evals import local_project, rq_eval


async def run_dataset(name: str, tmp: Path, client: Any = None) -> dict[str, Any]:
    db = tmp / f"{name}.duckdb"
    ctx, assoc = local_project.build_with_associations(db, [name])
    ids = count(1)

    async def execute(sql: str, limit: int) -> tuple[int, QueryResult]:
        return next(ids), run_query(db, sql, [name], row_limit=limit)

    questions = [
        Question(i, c["question"], Mapping.model_validate(c["gold_mapping"]))
        for i, c in enumerate(rq_eval.load_cases(), start=1)
        if c["tables"] == [name]
    ]
    g = await generate(ctx, execute, questions=questions, associations=assoc, client=client)
    analyses = [x for x in g.insights if x.kind == "analysis"]
    ungrounded = [x.statement for x in analyses if not (x.grounding and x.grounding["ok"])]
    return {
        "dataset": name,
        "planned": g.planned,
        "insights": len(analyses),
        "findings": sum(x.status == "finding" for x in analyses),
        "no_evidence": sum(x.status == "no_evidence" for x in analyses),
        "data_quality": len(g.insights) - len(analyses),
        "with_chart": sum(bool(x.chart and x.chart["data"]) for x in analyses),
        "confounder_flags": sum(
            any(c["verdict"] != "holds" for c in (x.result or {}).get("confounders", []))
            for x in analyses
        ),
        "failed": g.failed,
        "ungrounded": ungrounded,
        "top": [x.statement for x in analyses[:3]],
    }


def summarise(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    total = sum(r["insights"] for r in results)
    bad = sum(len(r["ungrounded"]) for r in results)
    lines = [
        f"# Insights check {meta['started']}",
        "",
        f"LLM: `{meta['llm']}` · git: `{meta['git_sha']}`",
        "",
        f"**{total} insights across {len(results)} datasets; {bad} with an untraceable number.**",
        "",
        "| Dataset | Planned | Insights | Findings | No evidence | Data quality | Charts | "
        "Confounder flags | Failed |",
        "|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {r['dataset']} | {r['planned']} | {r['insights']} | {r['findings']} | "
            f"{r['no_evidence']} | {r['data_quality']} | {r['with_chart']} | "
            f"{r['confounder_flags']} | {len(r['failed'])} |"
            for r in results
        ],
        "",
        "## Top insight per dataset",
        "",
        *[f"- **{r['dataset']}**: {r['top'][0] if r['top'] else '(none)'}" for r in results],
    ]
    failed = [f"- {r['dataset']}: {f}" for r in results for f in r["failed"]]
    if failed:
        lines += ["", "## Analyses that could not run", "", *failed]
    return "\n".join(lines) + "\n"


def report_json(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    return json.dumps({"meta": meta, "results": results}, indent=1, default=str) + "\n"
