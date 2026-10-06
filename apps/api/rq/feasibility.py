"""Feasibility checks for one research question: measured with SQL, never estimated.

Every number used by the verdict rules comes from a query run through the SQL guard and logged,
so each piece of evidence links to the query that produced it. Checks run on one table, the
table of the outcome construct (see DECISIONS.md).
"""

import datetime as dt
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from api.agent.tools import ColumnInfo, ProjectContext, TableInfo
from api.ingest.names import quote
from api.rq.schemas import CORE_ROLES, Candidate, Kind, MappedConstruct, Mapping, ParsedRQ
from api.rq.verdict import ConstructStatus, Measurements
from api.sql.executor import QueryResult

# (sql, row limit) -> (query id, result); query ids are None when nothing is logged
Execute = Callable[[str, int], Awaitable[tuple[int | None, QueryResult]]]

GROUP_LIMIT = 50
MAX_GROUPING_DISTINCT = 20  # a numeric column with this few values can act as groups
MAX_CONFOUNDERS = 5
CONFOUNDER_MIN = 0.1


@dataclass
class Resolved:
    """A construct with the column or expression chosen for it."""

    construct: MappedConstruct
    candidate: Candidate | None
    expression: str | None
    kind: Kind | None
    error: str | None = None


@dataclass
class Report:
    measurements: Measurements
    facts: list[dict[str, Any]] = field(default_factory=list)  # neutral evidence for display
    errors: list[str] = field(default_factory=list)


def chosen(construct: MappedConstruct) -> Candidate | None:
    if construct.status == "rejected" or not construct.candidates:
        return None
    return construct.candidates[0]


def kind_of(column: ColumnInfo) -> Kind:
    st = column.semantic_type or ""
    if st in ("numeric", "categorical", "datetime", "boolean"):
        return st  # type: ignore[return-value]
    if st == "free_text":
        return "text"
    if any(t in column.physical_type for t in ("INT", "DOUBLE", "DECIMAL", "FLOAT", "REAL")):
        return "numeric"
    if "DATE" in column.physical_type or "TIMESTAMP" in column.physical_type:
        return "datetime"
    return "categorical"


def resolve(ctx: ProjectContext, construct: MappedConstruct) -> Resolved:
    cand = chosen(construct)
    if cand is None:
        return Resolved(construct, None, None, None)
    try:
        table = ctx.table(cand.table)
    except ValueError as exc:
        return Resolved(construct, None, None, None, str(exc))
    if cand.match == "derivable" and cand.expression:
        return Resolved(construct, cand, f"({cand.expression})", cand.kind or "numeric")
    col = _column(table, cand.column)
    if col is None:
        return Resolved(
            construct, None, None, None, f"Table {table.table} has no column {cand.column!r}."
        )
    return Resolved(construct, cand, quote(col.name), cand.kind or kind_of(col))


def _column(table: TableInfo, name: str | None) -> ColumnInfo | None:
    if not name:
        return None
    return next((c for c in table.columns if c.name.lower() == name.lower()), None)


def _date(text: str | None) -> dt.date | None:
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def time_condition(table: TableInfo, mapping: Mapping) -> tuple[str | None, ColumnInfo | None]:
    """SQL condition for the time scope, and the time column."""
    col = _column(table, mapping.time_column)
    start, end = _date(mapping.time_start), _date(mapping.time_end)
    if col is None or (start is None and end is None):
        return None, col
    c = quote(col.name)
    parts = []
    if kind_of(col) == "numeric":  # a year column
        if start:
            parts.append(f"{c} >= {start.year}")
        if end:
            parts.append(f"{c} <= {end.year}")
    else:
        if start:
            parts.append(f"CAST({c} AS DATE) >= DATE '{start.isoformat()}'")
        if end:
            parts.append(f"CAST({c} AS DATE) <= DATE '{end.isoformat()}'")
    return " AND ".join(parts), col


async def measure(
    ctx: ProjectContext,
    parsed: ParsedRQ,
    mapping: Mapping,
    execute: Execute,
    associations: Sequence[dict[str, Any]] = (),
) -> Report:
    resolved = [resolve(ctx, c) for c in mapping.constructs]
    statuses = [
        ConstructStatus(
            name=r.construct.name,
            role=r.construct.role,
            match=r.candidate.match if r.candidate else None,
            table=r.candidate.table if r.candidate else None,
        )
        for r in resolved
    ]
    m = Measurements(rq_type=parsed.type, constructs=statuses)
    report = Report(m, errors=[r.error for r in resolved if r.error])

    outcome = next((r for r in resolved if r.construct.role == "dependent" and r.candidate), None)
    primary = outcome or next((r for r in resolved if r.candidate), None)
    if primary is None or primary.candidate is None:
        return report  # nothing mapped: the gap rules decide
    table = ctx.table(primary.candidate.table)
    t = quote(table.table)
    local = [
        (r, s)
        for r, s in zip(resolved, statuses, strict=True)
        if r.candidate and r.candidate.table.lower() == table.table.lower()
    ]

    async def run(name: str, sql: str, limit: int = 100) -> QueryResult | None:
        query_id, result = await execute(sql, limit)
        if result.error:
            report.errors.append(f"{name}: {result.error}")
            return None
        if query_id is not None:
            m.query_ids[name] = query_id
        return result

    # Derived expressions must run before they are used in checks.
    for r, s in local:
        if r.candidate and r.candidate.match == "derivable":
            check = await run(
                f"expr:{r.construct.name}", f"SELECT {r.expression} AS v FROM {t} LIMIT 1"
            )
            if check is None:
                s.match, s.table = None, None
                r.expression = None
    local = [(r, s) for r, s in local if r.expression]

    conditions = []
    if mapping.population_filter and mapping.population_filter.strip():
        conditions.append(f"({mapping.population_filter})")
    time_cond, time_col = time_condition(table, mapping)
    if time_cond:
        conditions.append(f"({time_cond})")
    scope = " AND ".join(conditions) or "TRUE"

    # 1. Rows in scope
    rows = await run(
        "rows",
        f"SELECT count(*) AS total_rows, count(*) FILTER (WHERE {scope}) AS rows_in_scope FROM {t}",
    )
    if rows is None:
        return report  # a broken filter: reported as an error, no measurements
    m.total_rows, m.rows_in_scope = (int(v) for v in rows.rows[0])
    report.facts.append(
        {
            "fact": "rows",
            "message": f"{m.total_rows} rows in {table.table}; "
            f"{m.rows_in_scope} in scope after filters.",
            "query_id": m.query_ids.get("rows"),
        }
    )

    # 2. Missing values and complete cases
    if local:
        present = ", ".join(f"count({r.expression}) AS c{i}" for i, (r, _) in enumerate(local))
        all_present = " AND ".join(f"{r.expression} IS NOT NULL" for r, _ in local)
        missing = await run(
            "missing",
            f"SELECT count(*) AS n, {present}, "
            f"count(*) FILTER (WHERE {all_present}) AS complete_cases FROM {t} WHERE {scope}",
        )
        if missing is not None:
            row = missing.rows[0]
            n_scope = int(row[0])
            for (_, s), present_n in zip(local, row[1:-1], strict=True):
                s.missing_share = 1 - int(present_n) / n_scope if n_scope else None
                s.query_id = m.query_ids.get("missing")
            m.complete_cases = int(row[-1])
            report.facts.append(
                {
                    "fact": "complete_cases",
                    "query_id": m.query_ids.get("missing"),
                    "message": f"{m.complete_cases} rows in scope have every mapped value.",
                }
            )
    complete = " AND ".join(f"{r.expression} IS NOT NULL" for r, _ in local) or "TRUE"

    # 3. Outcome variation
    if outcome and outcome.expression and any(r is outcome for r, _ in local):
        var = await run(
            "outcome",
            "SELECT count(*) AS distinct_values, max(n) * 1.0 / sum(n) AS top_share FROM "
            f"(SELECT {outcome.expression} AS v, count(*) AS n FROM {t} "
            f"WHERE {scope} AND {outcome.expression} IS NOT NULL GROUP BY 1) AS s",
        )
        if var is not None and var.rows and var.rows[0][0] is not None:
            m.outcome_distinct = int(var.rows[0][0])
            share = var.rows[0][1]
            m.outcome_top_share = float(share) if share is not None else None

    # 4. Groups
    grouping = _grouping(parsed, local, table)
    if grouping is not None:
        m.needs_groups = True
        outcome_distinct = (
            f"count(DISTINCT {outcome.expression})"
            if outcome and outcome.expression and outcome is not grouping
            else "NULL"
        )
        groups = await run(
            "groups",
            f"SELECT CAST({grouping.expression} AS VARCHAR) AS grp, count(*) AS n, "
            f"{outcome_distinct} AS outcome_values FROM {t} "
            f"WHERE {scope} AND {complete} GROUP BY 1 ORDER BY n DESC LIMIT {GROUP_LIMIT + 1}",
        )
        if groups is not None:
            m.groups = [(str(g), int(n)) for g, n, _ in groups.rows]
            m.constant_groups = [
                str(g) for g, n, k in groups.rows if k is not None and int(k) <= 1 and n > 1
            ]
            report.facts.append(
                {
                    "fact": "groups",
                    "query_id": m.query_ids.get("groups"),
                    "message": f"{len(m.groups)} groups of “{grouping.construct.name}”: "
                    + ", ".join(f"{g} ({n})" for g, n in m.groups[:8])
                    + (" …" if len(m.groups) > 8 else ""),
                }
            )
    else:
        m.correlational = any(
            r.construct.role == "independent" and r.kind == "numeric" for r, _ in local
        )

    # 5. Time coverage
    start, end = _date(mapping.time_start), _date(mapping.time_end)
    if time_col is not None and (start or end):
        tc = quote(time_col.name)
        span = await run("time", f"SELECT min({tc}) AS first, max({tc}) AS last FROM {t}")
        if span is not None and span.rows and span.rows[0][0] is not None:
            first, last = (_as_date(v) for v in span.rows[0])
            m.time_data = (str(span.rows[0][0]), str(span.rows[0][1]))
            m.time_requested = (mapping.time_start, mapping.time_end)
            m.time_coverage = _coverage(start or first, end or last, first, last)

    # 6. Possible confounders, from the profile's associations
    m.confounders = _confounders(local, associations)
    return report


def _grouping(
    parsed: ParsedRQ, local: list[tuple[Resolved, ConstructStatus]], table: TableInfo
) -> Resolved | None:
    """The construct that splits rows into groups, if the question compares groups."""
    for r, _ in local:
        if r.construct.role != "independent":
            continue
        if r.kind in ("categorical", "boolean"):
            return r
        if r.kind == "numeric" and r.candidate and r.candidate.column:
            col = _column(table, r.candidate.column)
            distinct = (col.profile or {}).get("distinct", 0) if col else 0
            if parsed.type == "comparative" and 0 < distinct <= MAX_GROUPING_DISTINCT:
                return r
    return None


def _as_date(v: Any) -> dt.date | None:
    if isinstance(v, int | float):
        return dt.date(int(v), 1, 1) if 1000 <= v <= 9999 else None
    return _date(str(v))


def _coverage(
    start: dt.date | None, end: dt.date | None, first: dt.date | None, last: dt.date | None
) -> float | None:
    if None in (start, end, first, last):
        return None
    assert start and end and first and last
    if end < start:
        return None
    if last < start or first > end:
        return 0.0
    overlap = (min(end, last) - max(start, first)).days + 1
    return min(1.0, overlap / ((end - start).days + 1))


def _confounders(
    local: list[tuple[Resolved, ConstructStatus]], associations: Sequence[dict[str, Any]]
) -> list[str]:
    def col(r: Resolved) -> str | None:
        return r.candidate.column if r.candidate and r.candidate.match != "derivable" else None

    outcome = [col(r) for r, _ in local if r.construct.role == "dependent"]
    explanatory = [col(r) for r, _ in local if r.construct.role == "independent"]
    mapped = {col(r) for r, _ in local}
    if not any(outcome) or not any(explanatory):
        return []

    linked: dict[str, set[str]] = {}
    for a in associations:
        if abs(float(a.get("value", 0))) < CONFOUNDER_MIN:
            continue
        x, y = str(a.get("a")), str(a.get("b"))
        linked.setdefault(x, set()).add(y)
        linked.setdefault(y, set()).add(x)
    found = [
        c
        for c, partners in linked.items()
        if c not in mapped
        and any(o in partners for o in outcome if o)
        and any(e in partners for e in explanatory if e)
    ]
    return sorted(found)[:MAX_CONFOUNDERS]


def core_mapped(mapping: Mapping) -> bool:
    return all(chosen(c) is not None for c in mapping.constructs if c.role in CORE_ROLES)
