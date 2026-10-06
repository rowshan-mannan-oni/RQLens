"""Generate a project's insights: plan, run, correct, rank, check confounders, write.

The LLM is optional. Without it, the plan comes from research questions and the profile, and
statements use the template, so insights work with no API key and every number on a card comes
from its own test result.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from api.agent import grounding
from api.agent.tools import ProjectContext
from api.insights import confounders, planner, writer
from api.insights.ranking import Ranked, rank
from api.insights.runner import Execute, Outcome, run_spec
from api.llm.client import LLMClient
from api.rq.schemas import Mapping
from api.stats.library import TestResult

log = logging.getLogger(__name__)

CONFOUNDER_TOP = 5
CONFIG_VERSION = f"{planner.PLAN_VERSION}+{writer.WRITE_VERSION}+ranking.v1"

# Rules from RQ assessments that become data-quality insights for that question.
DATA_QUALITY_RULES = {
    "high_missing", "small_group", "unbalanced_groups", "outcome_near_constant",
    "group_constant_outcome", "partial_time_coverage", "too_few_complete", "small_sample",
    "outcome_constant", "too_few_groups",
}  # fmt: skip


@dataclass
class Question:
    id: int
    text: str
    mapping: Mapping | None
    rules: list[dict[str, Any]] = field(default_factory=list)  # latest assessment's rules


@dataclass
class InsightRecord:
    kind: str  # analysis | data_quality
    status: str  # finding | weak | no_evidence | data_quality
    title: str
    statement: str
    rq_id: int | None
    score: float
    caveats: list[str]
    query_ids: list[int]
    sql: str | None = None
    spec: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    effect_size: float | None = None
    p_value: float | None = None
    p_adjusted: float | None = None
    grounding: dict[str, Any] | None = None
    written_by: str = "template"  # template | llm


@dataclass
class Generated:
    insights: list[InsightRecord]
    planned: int
    failed: list[str]
    dropped: list[str]


async def generate(
    ctx: ProjectContext,
    execute: Execute,
    *,
    questions: Sequence[Question] = (),
    associations: dict[str, list[dict[str, Any]]] | None = None,
    client: LLMClient | None = None,
) -> Generated:
    associations = associations or {}
    mapped = [(q.id, q.mapping) for q in questions if q.mapping is not None]
    from_rqs = planner.rq_specs(ctx, mapped)
    from_profile = planner.profile_specs(ctx, associations)
    from_llm = []
    if client is not None:
        try:
            from_llm = await planner.llm_specs(client, ctx, [q.text for q in questions], from_rqs)
        except Exception as exc:  # planning ideas are optional
            log.warning("insight planner failed, using rules only: %s", exc)
    plan, dropped = planner.combine(
        ctx, from_rqs, from_llm, from_profile, alias=planner.aliases(associations)
    )

    outcomes: list[Outcome] = [await run_spec(ctx, spec, execute) for spec in plan]
    failed = [f"{o.spec.table}: {o.spec.x} / {o.spec.y}: {o.error}" for o in outcomes if o.error]
    mapped_columns = {
        (c.candidates[0].table, c.candidates[0].column or "")
        for _, m in mapped
        for c in m.constructs
        if c.candidates and c.status != "rejected"
    }
    ranked = rank(outcomes, mapped_columns)

    checks: dict[int, list[dict[str, Any]]] = {}
    for i, r in enumerate(ranked[:CONFOUNDER_TOP]):
        if r.status == "no_evidence":
            continue
        found = []
        for z in confounders.candidates(ctx, r.outcome, associations.get(r.outcome.spec.table, [])):
            c = await confounders.check(ctx, r.outcome, z, execute)
            if c is not None:
                found.append(c)
        checks[i] = found

    records = [_record(ctx, r, checks.get(i, [])) for i, r in enumerate(ranked)]
    if client is not None and records:
        try:
            rewrites = await writer.rewrite(
                client,
                [{"title": x.title, "statement": x.statement, "result": x.result} for x in records],
                ctx.project_id or None,
            )
        except Exception as exc:
            log.warning("insight writing failed, keeping template statements: %s", exc)
            rewrites = {}
        for i, (text, check) in rewrites.items():  # each already checked against its result
            records[i].statement, records[i].grounding = text, check
            records[i].written_by = "llm"

    records += _data_quality(questions)
    return Generated(records, len(plan), failed, dropped)


def _record(ctx: ProjectContext, r: Ranked, found: list[dict[str, Any]]) -> InsightRecord:
    o: Outcome = r.outcome
    res: TestResult | None = o.result
    assert res is not None
    title, statement = writer.title_and_statement(ctx, r)
    result = res.to_json() | {
        "p_adjusted": r.p_adjusted,
        "magnitude": r.magnitude,
        "score_parts": {"relevance": r.relevance, "effect": r.effect, "support": r.support},
        "confounders": found,
    }
    return InsightRecord(
        kind="analysis",
        status=r.status,
        title=title,
        statement=statement,
        rq_id=o.spec.rq_id,
        score=r.score,
        caveats=writer.caveats(r, found) + _placeholder_caveats(ctx, o),
        query_ids=o.query_ids,
        sql=o.sql,
        spec=o.spec.model_dump(),
        result=result,
        chart=o.chart,
        effect_size=res.effect_size,
        p_value=res.p_value,
        p_adjusted=r.p_adjusted,
        grounding=grounding.check(statement, grounding.collect_numbers(result)).to_json(),
    )


def _placeholder_caveats(ctx: ProjectContext, o: Outcome) -> list[str]:
    """Warn when an analysed column holds codes such as -999 that the profiler flagged."""
    out = []
    table = ctx.table(o.spec.table)
    for name in (o.spec.x, o.spec.y):
        c = next((c for c in table.columns if c.name == name), None)
        codes = (((c.profile or {}).get("numeric") or {}).get("sentinels") or []) if c else []
        if codes:
            values = ", ".join(str(s["value"]) for s in codes)
            out.append(
                f"{c.label or name if c else name} contains {values}, which may be a code for "
                "missing; it was included in this test."
            )
    return out


def _data_quality(questions: Sequence[Question]) -> list[InsightRecord]:
    out = []
    for q in questions:
        for rule in q.rules:
            if rule.get("rule") not in DATA_QUALITY_RULES or rule.get("level") not in (
                "warn",
                "fail",
            ):
                continue
            qid = rule.get("query_id")
            out.append(
                InsightRecord(
                    kind="data_quality",
                    status="data_quality",
                    title=f"Data quality for: {q.text}",
                    statement=str(rule.get("message")),
                    rq_id=q.id,
                    score=0.0,
                    caveats=[],
                    query_ids=[qid] if isinstance(qid, int) else [],
                    result={"rule": rule.get("rule"), "level": rule.get("level")},
                )
            )
    return out
