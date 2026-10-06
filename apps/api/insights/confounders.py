"""Check whether a finding holds within subgroups of a likely confounder.

Candidate confounders are grouping columns of the same table (2 to MAX_LEVELS values) that the
profile found associated with both analysed columns. The same test is re-run within each
subgroup with at least MIN_STRATUM rows; at least MIN_STRATA subgroups are needed.
Verdicts (see DECISIONS.md):

- reverses: the effect has the opposite sign in a subgroup, with |effect| >= 0.1 (signed
  measures only: rho, tau, rank-biserial);
- weakens: the row-weighted mean |effect| within subgroups is under half the overall |effect|;
- holds: otherwise.
"""

from collections.abc import Sequence
from typing import Any

from api.agent.tools import ProjectContext
from api.ingest.names import quote
from api.insights.runner import STAT_ROWS, Execute, Outcome, scope
from api.insights.spec import column, distinct, is_grouping, usable
from api.stats.library import StatTestError, run_test

MAX_LEVELS = 6
MIN_STRATUM = 30
MIN_STRATA = 2
MAX_CANDIDATES = 2
MIN_LINK = 0.1
SIGNED = {"rho", "tau", "rank_biserial"}


def candidates(
    ctx: ProjectContext, outcome: Outcome, associations: Sequence[dict[str, Any]]
) -> list[str]:
    spec = outcome.spec
    table = ctx.table(spec.table)
    links: dict[str, dict[str, float]] = {}
    for a in associations:
        x, y, v = str(a.get("a")), str(a.get("b")), abs(float(a.get("value") or 0))
        links.setdefault(x, {})[y] = v
        links.setdefault(y, {})[x] = v
    scored = []
    for c in table.columns:
        if c.name in (spec.x, spec.y) or not usable(c) or not is_grouping(c):
            continue
        if distinct(c) > MAX_LEVELS:
            continue
        lx = links.get(c.name, {}).get(spec.x, 0.0)
        ly = links.get(c.name, {}).get(spec.y, 0.0)
        if lx >= MIN_LINK and ly >= MIN_LINK:
            scored.append((lx + ly, c.name))
    scored.sort(reverse=True)
    return [name for _, name in scored[:MAX_CANDIDATES]]


async def check(
    ctx: ProjectContext, outcome: Outcome, confounder: str, execute: Execute
) -> dict[str, Any] | None:
    spec, overall = outcome.spec, outcome.result
    if overall is None or column(ctx.table(spec.table), confounder) is None:
        return None
    t, x, y, z = (quote(n) for n in (spec.table, spec.x, spec.y, confounder))
    sql = (
        f"SELECT * FROM (SELECT {x} AS x, {y} AS y, CAST({z} AS VARCHAR) AS z FROM {t} "
        f"WHERE {scope(spec, spec.x, spec.y, confounder)}) AS s "
        f"USING SAMPLE reservoir({STAT_ROWS} ROWS) REPEATABLE (42)"
    )
    query_id, r = await execute(sql, STAT_ROWS)
    if query_id is not None:
        outcome.query_ids.append(query_id)
    if r.error:
        return None
    by_level: dict[str, list[tuple[Any, Any]]] = {}
    for xv, yv, zv in r.rows:
        by_level.setdefault(str(zv), []).append((xv, yv))

    strata: list[dict[str, Any]] = []
    for level, pairs in sorted(by_level.items(), key=lambda kv: -len(kv[1])):
        if len(pairs) < MIN_STRATUM:
            continue
        try:
            res = run_test(spec.test, [p[0] for p in pairs], [p[1] for p in pairs])
        except StatTestError:
            continue
        strata.append({"value": level, "n": res.n, "effect": res.effect_size})
    if len(strata) < MIN_STRATA:
        return None  # one subgroup cannot show whether the pattern holds across them

    name, e = overall.effect_size_name, overall.effect_size
    verdict = "holds"
    if name in SIGNED and any(s["effect"] * e < 0 and abs(s["effect"]) >= 0.1 for s in strata):
        verdict = "reverses"
    else:
        total = sum(s["n"] for s in strata)
        within = sum(abs(s["effect"]) * s["n"] for s in strata) / total
        if abs(e) > 0 and within < 0.5 * abs(e):
            verdict = "weakens"
    return {"column": confounder, "verdict": verdict, "strata": strata, "query_id": query_id}


def caveat(c: dict[str, Any]) -> str | None:
    if c["verdict"] == "reverses":
        return (
            f"The pattern reverses within some groups of {c['column']}; "
            f"{c['column']} may confound it."
        )
    if c["verdict"] == "weakens":
        return (
            f"The pattern is much weaker within groups of {c['column']}; "
            f"{c['column']} may explain part of it."
        )
    return None
