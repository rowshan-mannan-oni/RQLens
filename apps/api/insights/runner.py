"""Run analysis specs: a guarded query feeds a test from the fixed library, and a second query
shapes the data for a chart. Both queries are logged so each insight links to them.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from api.agent.tools import ProjectContext
from api.ingest.names import quote
from api.insights.spec import AnalysisSpec, column
from api.rq.feasibility import kind_of
from api.sql.executor import QueryResult
from api.stats.library import StatTestError, TestResult, run_test

# (sql, row limit) -> (query id or None, result)
Execute = Callable[[str, int], Awaitable[tuple[int | None, QueryResult]]]

STAT_ROWS = 100_000
SCATTER_POINTS = 300
CHART_CATEGORIES = 20
CHART_SERIES = 4  # the chart component draws at most 4 series
PERIODS = ("day", "week", "month", "quarter", "year")


@dataclass
class Outcome:
    spec: AnalysisSpec
    result: TestResult | None = None
    error: str | None = None
    query_ids: list[int] = field(default_factory=list)
    sql: str | None = None
    sampled_from: int | None = None  # rows before sampling, when the test used a sample
    chart: dict[str, Any] | None = None


def scope(spec: AnalysisSpec, *columns: str) -> str:
    conditions = [f"{quote(c)} IS NOT NULL" for c in columns]
    if spec.where and spec.where.strip():
        conditions.insert(0, f"({spec.where})")
    return " AND ".join(conditions)


async def run_spec(ctx: ProjectContext, spec: AnalysisSpec, execute: Execute) -> Outcome:
    out = Outcome(spec)
    t, x, y = quote(spec.table), quote(spec.x), quote(spec.y)
    where = scope(spec, spec.x, spec.y)
    sql = (
        f"SELECT * FROM (SELECT {x} AS x, {y} AS y FROM {t} WHERE {where}) AS s "
        f"USING SAMPLE reservoir({STAT_ROWS} ROWS) REPEATABLE (42)"
    )
    query_id, r = await execute(sql, STAT_ROWS)
    out.sql = r.sql
    if query_id is not None:
        out.query_ids.append(query_id)
    if r.error:
        out.error = r.error
        return out
    if r.row_count > STAT_ROWS:
        out.sampled_from = r.row_count
    try:
        out.result = run_test(spec.test, [row[0] for row in r.rows], [row[1] for row in r.rows])
    except StatTestError as exc:
        out.error = str(exc)
        return out
    out.chart = await _chart(ctx, spec, execute, out)
    return out


async def _chart(
    ctx: ProjectContext, spec: AnalysisSpec, execute: Execute, out: Outcome
) -> dict[str, Any] | None:
    assert out.result is not None
    t, x, y = quote(spec.table), quote(spec.x), quote(spec.y)
    where = scope(spec, spec.x, spec.y)
    title = f"{spec.y} by {spec.x}"

    if spec.test in ("mann_whitney", "kruskal_wallis"):
        # Group medians come straight from the test result (same query).
        data = [
            {spec.y: g["group"], "median": g["median"], "n": g["n"]}
            for g in out.result.groups[:CHART_CATEGORIES]
        ]
        query_id = out.query_ids[0] if out.query_ids else None
        return _spec("bar", f"Median {spec.x} by {spec.y}", spec.y, ["median"], data, query_id)

    if spec.test == "spearman":
        sql = (
            f"SELECT {x} AS {x}, {y} AS {y} FROM {t} WHERE {where} "
            f"USING SAMPLE reservoir({SCATTER_POINTS} ROWS) REPEATABLE (42)"
        )
        kind, cols = "scatter", [spec.y]
    elif spec.test == "trend":
        table = ctx.table(spec.table)
        col = column(table, spec.x)
        bucket = x
        if col is not None and kind_of(col) == "datetime":
            period = ((col.profile or {}).get("datetime") or {}).get("period") or "month"
            if period not in PERIODS:
                period = "month"
            bucket = f"date_trunc('{period}', {x})"
        sql = (
            f"SELECT {bucket} AS {x}, avg({y}) AS mean_{spec.y}, count(*) AS n FROM {t} "
            f"WHERE {where} GROUP BY 1 ORDER BY 1"
        )
        kind, cols, title = "line", [f"mean_{spec.y}"], f"Mean {spec.y} over {spec.x}"
    else:  # chi_square: share of each y value within each x value
        sql = (
            "SELECT a, b, n, round(100.0 * n / sum(n) OVER (PARTITION BY a), 1) AS pct FROM "
            f"(SELECT CAST({x} AS VARCHAR) AS a, CAST({y} AS VARCHAR) AS b, count(*) AS n "
            f"FROM {t} WHERE {where} GROUP BY 1, 2) AS c ORDER BY a, n DESC"
        )
        query_id, r = await execute(sql, 2000)
        if query_id is not None:
            out.query_ids.append(query_id)
        if r.error:
            return None
        series = _top([row[1] for row in r.rows], [row[2] for row in r.rows], CHART_SERIES)
        wide: dict[str, dict[str, Any]] = {}
        for a, b, _, pct in r.rows:
            if b in series:
                wide.setdefault(a, {spec.x: a})[f"% {b}"] = pct
        data = list(wide.values())[:CHART_CATEGORIES]
        return _spec(
            "bar", f"Share of {spec.y} within {spec.x}", spec.x, [f"% {b}" for b in series],
            data, query_id,
        )  # fmt: skip

    query_id, r = await execute(sql, 2000)
    if query_id is not None:
        out.query_ids.append(query_id)
    if r.error:
        return None
    data = [dict(zip(r.columns, row, strict=True)) for row in r.rows]
    return _spec(kind, title, spec.x, cols, data, query_id)


def _top(labels: list[Any], counts: list[Any], k: int) -> list[str]:
    totals: dict[str, int] = {}
    for label, n in zip(labels, counts, strict=True):
        totals[str(label)] = totals.get(str(label), 0) + int(n)
    return [label for label, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:k]]


def _spec(
    kind: str, title: str, x: str, y: list[str], data: list[dict[str, Any]], query_id: int | None
) -> dict[str, Any]:
    return {
        "id": 1, "type": kind, "title": title, "x": x, "y": y, "data": data,
        "query_id": query_id, "truncated": False,
    }  # fmt: skip
