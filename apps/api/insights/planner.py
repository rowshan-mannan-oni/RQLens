"""Plan up to MAX_ANALYSES analyses for a project.

1. From research questions: each mapped outcome against each mapped explanatory variable,
   with the question's population filter. These are the most relevant analyses.
2. From the LLM (optional): ideas that relate to the research topic and questions.
3. From the profile: the strongest associations the profiler found, to fill the remaining slots.

Category pairs associated at Cramér's V >= 0.9 are left out of the profile ideas: one column
usually recodes the other (titanic's `who` and `sex`). Any pair at >= 0.98 is left out as a
near-duplicate. Strong numeric correlations are kept, because they can be real findings.
Columns that are near-perfect copies of each other (|value| >= 0.95, such as titanic's pclass
and class) are treated as one column when removing duplicate analyses.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from api.agent.tools import ProjectContext
from api.insights.spec import AnalysisSpec, Plan, choose_test, column, usable, validate
from api.llm.client import LLMClient
from api.rq.mapper import schema_for
from api.rq.schemas import Mapping

MAX_ANALYSES = 20
MAX_LLM = 8
RECODED_CATEGORIES = 0.9
NEAR_DUPLICATE = 0.98
ALIAS = 0.95
MIN_ASSOCIATION = 0.1
PLAN_VERSION = "insights_plan.v1"
PROMPT = Path(__file__).parent.parent / "prompts" / f"{PLAN_VERSION}.md"


def rq_specs(ctx: ProjectContext, questions: Sequence[tuple[int, Mapping]]) -> list[AnalysisSpec]:
    out = []
    for rq_id, mapping in questions:
        chosen = [
            (c.role, c.candidates[0])
            for c in mapping.constructs
            if c.status != "rejected" and c.candidates and c.candidates[0].column
        ]
        outcomes = [cand for role, cand in chosen if role == "dependent"]
        explanatory = [cand for role, cand in chosen if role == "independent"]
        for o in outcomes:
            for e in explanatory:
                if o.table != e.table or o.column is None or e.column is None:
                    continue
                table = next((t for t in ctx.tables if t.table == o.table), None)
                oc = column(table, o.column) if table else None
                ec = column(table, e.column) if table else None
                if oc is None or ec is None:
                    continue
                choice = choose_test(oc, ec)
                if choice is None:
                    continue
                test, x, y = choice
                out.append(
                    AnalysisSpec(
                        table=o.table, test=test, x=x, y=y, where=mapping.population_filter,
                        reason="Tests the research question directly.", rq_id=rq_id, source="rq",
                    )
                )  # fmt: skip
    return out


def profile_specs(
    ctx: ProjectContext, associations: dict[str, list[dict[str, Any]]]
) -> list[AnalysisSpec]:
    candidates = []
    for t in ctx.tables:
        for a in associations.get(t.table, []):
            value = abs(float(a.get("value") or 0))
            if value < MIN_ASSOCIATION or value >= NEAR_DUPLICATE:
                continue
            if a.get("measure") == "cramers_v" and value >= RECODED_CATEGORIES:
                continue
            ca, cb = column(t, str(a.get("a"))), column(t, str(a.get("b")))
            if ca is None or cb is None or not usable(ca) or not usable(cb):
                continue
            choice = choose_test(cb, ca) or choose_test(ca, cb)
            if choice is None:
                continue
            test, x, y = choice
            spec = AnalysisSpec(
                table=t.table, test=test, x=x, y=y, source="profile",
                reason=f"Strong association in the profile ({a.get('measure')} {value:.2f}).",
            )  # fmt: skip
            candidates.append((value, spec))
    candidates.sort(key=lambda c: -c[0])
    return [s for _, s in candidates]


async def llm_specs(
    client: LLMClient,
    ctx: ProjectContext,
    questions: Sequence[str],
    planned: Sequence[AnalysisSpec],
) -> list[AnalysisSpec]:
    schema = await schema_for(ctx, " ".join([ctx.topic or "", *questions]))
    content = (
        f"<topic>\n{ctx.topic or ''}\n</topic>\n"
        f"<research_questions>\n{json.dumps(list(questions), ensure_ascii=False)}\n"
        "</research_questions>\n"
        f"<already_planned>\n"
        + json.dumps([s.model_dump(include={"table", "test", "x", "y"}) for s in planned])
        + "\n</already_planned>\n"
        f"<schema>\n{json.dumps(schema, ensure_ascii=False, default=str)}\n</schema>"
    )
    result = await client.complete_structured(
        [
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {"role": "user", "content": content},
        ],
        Plan,
        step="insights_plan",
        prompt_version=PLAN_VERSION,
        project_id=ctx.project_id or None,
    )
    assert result.parsed is not None
    return [s.model_copy(update={"source": "llm", "rq_id": None}) for s in result.parsed.analyses][
        :MAX_LLM
    ]


def aliases(associations: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], str]:
    """(table, column) -> a representative column for groups of near-identical columns."""
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(k: tuple[str, str]) -> tuple[str, str]:
        while parent.get(k, k) != k:
            k = parent[k]
        return k

    for table, rows in associations.items():
        for a in rows:
            if abs(float(a.get("value") or 0)) >= ALIAS:
                ra, rb = find((table, str(a.get("a")))), find((table, str(a.get("b"))))
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    return {k: find(k)[1] for k in parent}


def combine(
    ctx: ProjectContext,
    *groups: Sequence[AnalysisSpec],
    limit: int = MAX_ANALYSES,
    alias: dict[tuple[str, str], str] | None = None,
) -> tuple[list[AnalysisSpec], list[str]]:
    """Validate, de-duplicate (same table and column pair, up to aliases) and cap, in order."""
    alias = alias or {}
    seen: set[tuple[str, frozenset[str]]] = set()
    plan: list[AnalysisSpec] = []
    dropped: list[str] = []
    for group in groups:
        for spec in group:
            checked, problem = validate(ctx, spec)
            if checked is None:
                dropped.append(f"{spec.table}.{spec.x} / {spec.y}: {problem}")
                continue
            t = checked.table
            key = (
                t.lower(),
                frozenset(alias.get((t, c), c).lower() for c in (checked.x, checked.y)),
            )
            if key in seen or len(plan) >= limit:
                continue
            seen.add(key)
            plan.append(checked)
    return plan, dropped
