"""Verdict rules for research-question fit. Pure functions; see DECISIONS.md for the table.

The verdict is the worst level among the rules that fire: any fail gives not_answerable,
otherwise any warn gives partial, otherwise answerable. Messages quote the measured numbers so
the explanation written from them passes the grounding check.
"""

import math
from dataclasses import dataclass, field

from api.rq.schemas import CORE_ROLES, RQType, RuleResult, Verdict

RULES_VERSION = "rules.v1"

MIN_COMPLETE = 10
SMALL_SAMPLE = 30
HIGH_MISSING = 0.30
MIN_GROUP_ROWS = 5
SMALL_GROUP = 20
UNBALANCED = 10.0
NEAR_CONSTANT = 0.95
TIME_COVERAGE = 0.80
LARGE_D = 0.8
LARGE_R = 0.5
LARGE_MARGIN = 0.1

Z_ALPHA = 1.959964  # two-sided 0.05
Z_POWER = 0.841621  # 80% power


@dataclass
class ConstructStatus:
    name: str
    role: str
    match: str | None  # direct | proxy | derivable, or None for a gap
    table: str | None = None
    query_id: int | None = None
    missing_share: float | None = None  # in scope


@dataclass
class Measurements:
    rq_type: RQType
    constructs: list[ConstructStatus]
    total_rows: int | None = None
    rows_in_scope: int | None = None
    complete_cases: int | None = None
    needs_groups: bool = False
    groups: list[tuple[str, int]] | None = None  # complete rows per group, largest first
    constant_groups: list[str] = field(default_factory=list)  # groups whose outcome never varies
    correlational: bool = False  # numeric explanatory variable
    outcome_distinct: int | None = None
    outcome_top_share: float | None = None
    time_requested: tuple[str | None, str | None] | None = None
    time_data: tuple[str | None, str | None] | None = None
    time_coverage: float | None = None  # share of the requested period the data covers
    confounders: list[str] = field(default_factory=list)
    query_ids: dict[str, int] = field(default_factory=dict)  # measurement -> query id


def min_detectable_d(n1: int, n2: int) -> float:
    return (Z_ALPHA + Z_POWER) * math.sqrt(1 / n1 + 1 / n2)


def min_detectable_r(n: int) -> float:
    return math.tanh((Z_ALPHA + Z_POWER) / math.sqrt(n - 3)) if n > 3 else 1.0


def margin_of_error(n: int) -> float:
    return Z_ALPHA * math.sqrt(0.25 / n) if n > 0 else 1.0


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def apply_rules(m: Measurements) -> list[RuleResult]:
    out: list[RuleResult] = []
    q = m.query_ids

    def fire(
        rule: str, level: str, message: str, query: str | None = None, **values: object
    ) -> None:
        out.append(
            RuleResult(
                rule=rule,
                level=level,
                message=message,
                query_id=q.get(query) if query else None,
                values=values,
            )
        )

    # Mapping
    for c in m.constructs:
        if c.match is None:
            if c.role in CORE_ROLES:
                fire("core_gap", "fail", f"No column in the data measures “{c.name}” ({c.role}).")
            else:
                fire("covariate_gap", "warn", f"No column measures the covariate “{c.name}”.")
        elif c.match == "proxy" and c.role in CORE_ROLES:
            fire("proxy_only", "warn", f"“{c.name}” is measured only through a proxy column.")
    tables = {c.table for c in m.constructs if c.table}
    if len(tables) > 1:
        fire(
            "multi_table",
            "warn",
            f"Constructs come from {len(tables)} tables ({', '.join(sorted(tables))}); "
            "checks used the outcome's table only.",
        )

    # Rows
    if m.rows_in_scope is not None and m.rows_in_scope == 0:
        fire(
            "no_rows_in_scope",
            "fail",
            "No rows remain after the population and time filters.",
            "rows",
            rows_in_scope=0,
        )
    n = m.complete_cases
    if n is not None and m.rows_in_scope:
        if n < MIN_COMPLETE:
            fire(
                "too_few_complete",
                "fail",
                f"Only {n} rows have every mapped column present; at least {MIN_COMPLETE} are "
                "needed.",
                "missing",
                complete_cases=n,
            )
        elif n < SMALL_SAMPLE:
            fire(
                "small_sample",
                "warn",
                f"Only {n} complete rows; results will be imprecise.",
                "missing",
                complete_cases=n,
            )
    for c in m.constructs:
        if c.missing_share is not None and c.missing_share > HIGH_MISSING:
            fire(
                "high_missing",
                "warn",
                f"“{c.name}” is missing in {_pct(c.missing_share)} of rows in scope.",
                "missing",
                construct=c.name,
                missing_share=c.missing_share,
            )

    # Outcome
    if m.outcome_distinct is not None and m.rows_in_scope:
        if m.outcome_distinct <= 1:
            fire(
                "outcome_constant",
                "fail",
                "The outcome has a single value in scope, so nothing can explain it.",
                "outcome",
                distinct=m.outcome_distinct,
            )
        elif m.outcome_top_share is not None and m.outcome_top_share >= NEAR_CONSTANT:
            fire(
                "outcome_near_constant",
                "warn",
                f"One outcome value covers {_pct(m.outcome_top_share)} of rows in scope.",
                "outcome",
                top_share=m.outcome_top_share,
            )

    # Groups
    usable_groups = [(g, k) for g, k in (m.groups or []) if k >= MIN_GROUP_ROWS]
    if m.needs_groups and m.groups is not None and n:
        if len(usable_groups) < 2:
            fire(
                "too_few_groups",
                "fail",
                f"Only {len(usable_groups)} group(s) have at least {MIN_GROUP_ROWS} complete "
                "rows; a comparison needs 2.",
                "groups",
                groups=len(usable_groups),
            )
        else:
            smallest, largest = usable_groups[-1][1], usable_groups[0][1]
            if smallest < SMALL_GROUP:
                fire(
                    "small_group",
                    "warn",
                    f"The smallest group (“{usable_groups[-1][0]}”) has {smallest} complete rows.",
                    "groups",
                    smallest=smallest,
                )
            if largest / smallest > UNBALANCED:
                fire(
                    "unbalanced_groups",
                    "warn",
                    f"Groups are unbalanced: {largest} versus {smallest} complete rows.",
                    "groups",
                    largest=largest,
                    smallest=smallest,
                )

    if m.constant_groups and m.needs_groups:
        names = ", ".join(f"“{g}”" for g in m.constant_groups[:5])
        fire(
            "group_constant_outcome",
            "warn",
            f"The outcome never varies within {names}. It may not be recorded for "
            "that group, which would make the comparison an artefact.",
            "groups",
            groups=m.constant_groups,
        )

    # Time
    if m.time_coverage is not None:
        if m.time_coverage <= 0:
            fire(
                "no_time_overlap",
                "fail",
                "The data's dates do not overlap the requested period.",
                "time",
            )
        elif m.time_coverage < TIME_COVERAGE:
            fire(
                "partial_time_coverage",
                "warn",
                f"The data covers {_pct(m.time_coverage)} of the requested period.",
                "time",
                coverage=m.time_coverage,
            )

    # Power (only when the basics hold)
    if not any(r.level == "fail" for r in out) and n:
        power = _power(m, usable_groups, n)
        if power is not None:
            fire(*power)

    # Causal wording
    if m.rq_type == "causal":
        fire(
            "causal_claim",
            "warn",
            "The question is causal, but observational data can show association only.",
        )
    if m.confounders:
        fire(
            "confounders",
            "info",
            f"Possible confounders (associated with both variables): {', '.join(m.confounders)}.",
        )
    return out


def _power(
    m: Measurements, groups: list[tuple[str, int]], n: int
) -> tuple[str, str, str, str] | None:
    if m.needs_groups and len(groups) >= 2:
        n1, n2 = groups[-1][1], groups[-2][1]
        d = min_detectable_d(n1, n2)
        if d > LARGE_D:
            return (
                "low_power",
                "warn",
                f"With the two smallest groups ({n2} and {n1} rows), only large differences "
                f"(Cohen's d of {d:.2f} or more) can be detected reliably.",
                "groups",
            )
        return None
    if m.correlational:
        r = min_detectable_r(n)
        if r > LARGE_R:
            return (
                "low_power",
                "warn",
                f"With {n} complete rows, only correlations of {r:.2f} or more can be "
                "detected reliably.",
                "missing",
            )
        return None
    if m.rq_type == "descriptive":
        margin = margin_of_error(n)
        if margin > LARGE_MARGIN:
            return (
                "low_power",
                "warn",
                f"With {n} complete rows, estimates have a margin of error of about "
                f"{margin:.2f} (as a proportion).",
                "missing",
            )
    return None


def decide(results: list[RuleResult]) -> Verdict:
    levels = {r.level for r in results}
    if "fail" in levels:
        return "not_answerable"
    if "warn" in levels:
        return "partial"
    return "answerable"
