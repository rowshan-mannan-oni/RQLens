"""Titles, statements and caveats for insights.

Every insight first gets a template statement built only from its own test result, so it is
always grounded. When an LLM is available it may rewrite the statements in plainer language;
each rewrite must pass the grounding check against that insight's numbers, or the template
statement is kept.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from api.agent import grounding
from api.agent.tools import ProjectContext
from api.insights.confounders import caveat
from api.insights.ranking import Ranked
from api.insights.spec import column
from api.llm.client import LLMClient

WRITE_VERSION = "insights_write.v1"
PROMPT = Path(__file__).parent.parent / "prompts" / f"{WRITE_VERSION}.md"

TEST_NAMES = {
    "spearman": "Spearman correlation",
    "mann_whitney": "Mann-Whitney U",
    "kruskal_wallis": "Kruskal-Wallis",
    "chi_square": "chi-square test",
    "trend": "Mann-Kendall trend test",
}
EFFECT_NAMES = {
    "rho": "rho",
    "tau": "Kendall's tau",
    "rank_biserial": "rank-biserial r",
    "cramers_v": "Cramér's V",
    "epsilon_squared": "epsilon squared",
}
EXPLORATORY = (
    "Exploratory: one of many patterns tested, so treat it as a hypothesis to test, not a result."
)


def label(ctx: ProjectContext, table: str, name: str) -> str:
    c = column(ctx.table(table), name)
    return (c.label or c.name) if c else name


def fmt(v: float) -> str:
    return f"{v:.3g}" if abs(v) < 1000 else f"{v:,.0f}"


def p_text(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}"


def title_and_statement(ctx: ProjectContext, r: Ranked) -> tuple[str, str]:
    spec, res = r.outcome.spec, r.outcome.result
    assert res is not None
    x, y = label(ctx, spec.table, spec.x), label(ctx, spec.table, spec.y)
    stats = (
        f"{TEST_NAMES[spec.test]}, {EFFECT_NAMES.get(res.effect_size_name, res.effect_size_name)}"
        f" = {fmt(res.effect_size)}, adjusted {p_text(r.p_adjusted)}, n = {res.n:,}"
    )
    if spec.test in ("mann_whitney", "kruskal_wallis"):
        title = f"{x} by {y}"
        groups = sorted(res.groups, key=lambda g: -g["median"])
        if r.status == "no_evidence":
            body = f"No clear difference in {x} between groups of {y}"
        else:
            top, bottom = groups[0], groups[-1]
            body = (
                f"{x} differs across {y}: median {fmt(top['median'])} for {top['group']} versus "
                f"{fmt(bottom['median'])} for {bottom['group']}"
            )
    elif spec.test == "chi_square":
        title = f"{y} and {x}"
        body = (
            f"No clear association between {x} and {y}"
            if r.status == "no_evidence"
            else f"{y} is distributed differently across {x}"
        )
    elif spec.test == "trend":
        title = f"{y} over {x}"
        direction = "upward" if res.effect_size > 0 else "downward"
        body = (
            f"No clear trend in {y} over {x}"
            if r.status == "no_evidence"
            else f"{y} shows a {r.magnitude} {direction} trend over {x}"
        )
    else:
        title = f"{y} and {x}"
        direction = "rise" if res.effect_size > 0 else "fall"
        body = (
            f"No clear relationship between {x} and {y}"
            if r.status == "no_evidence"
            else f"{y} tends to {direction} as {x} increases ({r.magnitude} effect)"
        )
    return title, f"{body} ({stats})."


def caveats(r: Ranked, confounders: list[dict[str, Any]]) -> list[str]:
    out = [EXPLORATORY]
    res = r.outcome.result
    if res is not None and res.note:
        out.append(res.note)
    if r.outcome.sampled_from:
        out.append(f"Tested on a random sample of rows ({r.outcome.sampled_from:,} available).")
    if r.outcome.spec.where:
        out.append(f"Only rows where {r.outcome.spec.where}.")
    out += [c for c in (caveat(x) for x in confounders) if c]
    if r.status != "no_evidence":
        out.append("An association in observational data, not evidence of cause.")
    return out


class Statement(BaseModel):
    index: int
    statement: str = Field(max_length=400)


class Statements(BaseModel):
    statements: list[Statement]


async def rewrite(
    client: LLMClient, items: list[dict[str, Any]], project_id: int | None = None
) -> dict[int, tuple[str, dict[str, Any]]]:
    """LLM rewrites keyed by item index, each with its grounding result; failures are absent."""
    payload = [
        {"index": i, "title": it["title"], "draft": it["statement"], "result": it["result"]}
        for i, it in enumerate(items)
    ]
    result = await client.complete_structured(
        [
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": "<insights>\n"
                + json.dumps(payload, ensure_ascii=False, default=str)
                + "\n</insights>",
            },
        ],
        Statements,
        step="insights_write",
        prompt_version=WRITE_VERSION,
        project_id=project_id,
    )
    assert result.parsed is not None
    out = {}
    for s in result.parsed.statements:
        if not 0 <= s.index < len(items):
            continue
        pool = grounding.collect_numbers(items[s.index]["result"], items[s.index]["statement"])
        check = grounding.check(s.statement, pool)
        if check.ok:
            out[s.index] = (s.statement, check.to_json())
    return out
