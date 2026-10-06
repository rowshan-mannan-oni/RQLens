"""Per-column profile, computed with plain SQL in DuckDB."""

import math
import re
import statistics
from typing import Any, Protocol

import duckdb

from api.ingest.names import quote
from api.profiler.warnings import SENTINEL_MIN_COUNT, SENTINEL_VALUES

INTEGER_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
}  # fmt: skip
FLOAT_TYPES = {"FLOAT", "REAL", "DOUBLE"}

HISTOGRAM_BINS = 20
TOP_VALUES = 10
# Numeric columns with at most this many distinct values also get value counts.
LOW_CARDINALITY = 50
# Integer columns with at most this many distinct values are treated as categories
# (Likert items, codes).
INTEGER_CATEGORY_LIMIT = 10
RARE_CATEGORY_SHARE = 0.01
SAMPLE_VALUES = 5
MAX_PERIODS = 400

# Unit checks
UNIT_SHIFT_CHUNKS = 10
UNIT_SHIFT_MIN_ROWS = 300
UNIT_SHIFT_RATIO = 2.0
UNIT_SHIFT_WITHIN = 1.3
# A number followed by a unit, e.g. "72 kg", "5.5ft", "30%".
UNIT_PATTERN = r"^[-+]?[0-9]*[.,]?[0-9]+\s*([A-Za-z%°µ][A-Za-z%°µ/²³0-9]*)$"


class ColumnLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def original_name(self) -> str: ...
    @property
    def physical_type(self) -> str: ...


ID_NAME = re.compile(r"(^|_)(id|uuid|guid|key)$|^id_")
BOOLEAN_PAIRS = [
    {"0", "1"},
    {"true", "false"},
    {"yes", "no"},
    {"y", "n"},
    {"t", "f"},
]


def kind_of(physical_type: str) -> str:
    p = physical_type.upper()
    if p == "BOOLEAN":
        return "boolean"
    if p in INTEGER_TYPES or p in FLOAT_TYPES or p.startswith("DECIMAL"):
        return "numeric"
    if p == "DATE" or p.startswith("TIMESTAMP"):
        return "datetime"
    if p == "VARCHAR":
        return "text"
    return "other"


def profile_column(
    con: duckdb.DuckDBPyConnection, table: str, column: ColumnLike, row_count: int
) -> dict[str, Any]:
    t, c = quote(table), quote(column.name)
    kind = kind_of(column.physical_type)
    non_null, distinct = _one(con, f"SELECT count({c}), count(DISTINCT {c}) FROM {t}")

    profile: dict[str, Any] = {
        "kind": kind,
        "physical_type": column.physical_type,
        "count": row_count,
        "non_null": non_null,
        "missing": row_count - non_null,
        "missing_pct": (row_count - non_null) / row_count if row_count else 0.0,
        "distinct": distinct,
        "uniqueness": distinct / non_null if non_null else 0.0,
    }

    if non_null:
        if kind == "numeric":
            profile["numeric"] = _numeric(con, t, c)
        elif kind == "datetime":
            profile["datetime"] = _datetime(con, t, c, column.physical_type)
        elif kind == "text":
            profile["text"] = _text(con, t, c)

        if kind in ("text", "boolean") or (kind == "numeric" and distinct <= LOW_CARDINALITY):
            profile["top_values"], profile["categorical"] = _categories(con, t, c, non_null)

    profile["semantic_type"] = semantic_type(column, profile)
    cleaned: dict[str, Any] = _clean(profile)
    return cleaned


def semantic_type(column: ColumnLike, p: dict[str, Any]) -> str:
    """One of: constant, boolean, datetime, identifier, categorical, numeric, free_text, other."""
    if p["distinct"] <= 1:
        return "constant"
    kind = p["kind"]
    top = {str(v["value"]).strip().lower() for v in p.get("top_values", [])}
    if kind == "boolean" or (p["distinct"] == 2 and top in BOOLEAN_PAIRS):
        return "boolean"
    if kind == "datetime":
        return "datetime"

    id_name = bool(ID_NAME.search(column.name))
    unique = p["uniqueness"] >= 0.95
    if kind == "numeric":
        integer = column.physical_type.upper() in INTEGER_TYPES
        if integer and id_name and unique:
            return "identifier"
        if integer and p["distinct"] <= INTEGER_CATEGORY_LIMIT and p["uniqueness"] <= 0.5:
            return "categorical"
        return "numeric"
    if kind == "text":
        text = p["text"]
        if id_name and unique:
            return "identifier"
        if text["avg_length"] >= 50 or (text["avg_words"] >= 4 and p["uniqueness"] >= 0.5):
            return "free_text"
        if unique and p["non_null"] >= 20 and text["avg_words"] <= 1.5:
            return "identifier"
        return "categorical"
    return "other"


def _numeric(con: duckdb.DuckDBPyConnection, t: str, c: str) -> dict[str, Any]:
    src = f"(SELECT {c}::DOUBLE AS x FROM {t} WHERE {c} IS NOT NULL AND isfinite({c}::DOUBLE))"
    row = con.execute(
        f"""
        SELECT count(x), min(x), max(x), avg(x), median(x), stddev_samp(x), skewness(x),
               quantile_cont(x, [0.05, 0.25, 0.5, 0.75, 0.95]),
               count_if(x = 0), count_if(x < 0)
        FROM {src}
        """
    ).fetchone()
    assert row is not None
    finite, lo, hi, mean, median, std, skew, qs, zeros, negatives = row
    if not finite:
        return {"finite": 0}

    q05, q25, q50, q75, q95 = qs
    iqr = q75 - q25
    fence_lo, fence_hi = q25 - 1.5 * iqr, q75 + 1.5 * iqr
    (outliers,) = _one(con, f"SELECT count_if(x < ? OR x > ?) FROM {src}", [fence_lo, fence_hi])

    sentinels = [
        {"value": v, "count": int(n)}
        for v, n in con.execute(
            f"SELECT x, count(*) FROM {src} WHERE x IN ({', '.join('?' * len(SENTINEL_VALUES))}) "
            "GROUP BY x ORDER BY x",
            list(SENTINEL_VALUES),
        ).fetchall()
        if n >= SENTINEL_MIN_COUNT and (v < fence_lo or v > fence_hi)
    ]

    return {
        "finite": finite,
        "min": lo,
        "max": hi,
        "mean": mean,
        "median": median,
        "std": std,
        "skew": skew,
        "quantiles": {"p05": q05, "p25": q25, "p50": q50, "p75": q75, "p95": q95},
        "zeros": zeros,
        "negatives": negatives,
        "zero_share": zeros / finite,
        "negative_share": negatives / finite,
        "outliers": outliers,
        "outlier_fences": [fence_lo, fence_hi],
        "sentinels": sentinels,
        "histogram": _histogram(con, src, lo, hi),
        "unit_shift": _unit_shift(con, t, c, finite),
    }


def _histogram(
    con: duckdb.DuckDBPyConnection, src: str, lo: float, hi: float
) -> list[dict[str, float]]:
    if lo == hi:
        (n,) = _one(con, f"SELECT count(*) FROM {src}")
        return [{"start": lo, "end": hi, "count": n}]
    width = (hi - lo) / HISTOGRAM_BINS
    counts = dict(
        con.execute(
            f"SELECT least(floor((x - ?) / ?)::BIGINT, ?) AS b, count(*) FROM {src} GROUP BY b",
            [lo, width, HISTOGRAM_BINS - 1],
        ).fetchall()
    )
    return [
        {"start": lo + i * width, "end": lo + (i + 1) * width, "count": counts.get(i, 0)}
        for i in range(HISTOGRAM_BINS)
    ]


def _unit_shift(
    con: duckdb.DuckDBPyConnection, t: str, c: str, finite: int
) -> dict[str, Any] | None:
    """Look for a lasting jump in scale partway through the file (e.g. kg switching to lb).

    Rows are split, in file order, into equal chunks; a shift is reported when chunk medians are
    stable on each side of a split but differ by at least UNIT_SHIFT_RATIO across it.
    """
    if finite < UNIT_SHIFT_MIN_ROWS:
        return None
    rows = con.execute(
        f"""
        SELECT k, median(x), min(r) FROM (
            SELECT ntile({UNIT_SHIFT_CHUNKS}) OVER (ORDER BY rowid) AS k, rowid AS r,
                   {c}::DOUBLE AS x
            FROM {t} WHERE {c} IS NOT NULL AND isfinite({c}::DOUBLE)
        ) GROUP BY k ORDER BY k
        """
    ).fetchall()
    medians = [float(m) for _, m, _ in rows]
    if not (all(m > 0 for m in medians) or all(m < 0 for m in medians)):
        return None
    sizes = [abs(m) for m in medians]

    best: dict[str, Any] | None = None
    for k in range(2, len(sizes) - 1):  # at least two chunks on each side
        before, after = sizes[:k], sizes[k:]
        within = max(max(before) / min(before), max(after) / min(after))
        ratio = statistics.median(after) / statistics.median(before)
        jump = max(ratio, 1 / ratio)
        stronger = best is None or jump > max(best["ratio"], 1 / best["ratio"])
        if jump >= UNIT_SHIFT_RATIO and within <= UNIT_SHIFT_WITHIN and stronger:
            best = {
                "from_row": int(rows[k][2]) + 1,
                "ratio": ratio,
                "median_before": statistics.median(medians[:k]),
                "median_after": statistics.median(medians[k:]),
            }
    return best


def _units(con: duckdb.DuckDBPyConnection, t: str, c: str) -> dict[str, Any] | None:
    """Text values that are numbers with a unit suffix, and which units appear."""
    rows = con.execute(
        f"SELECT u, count(*) AS n FROM (SELECT regexp_extract(trim({c}), ?, 1) AS u "
        f"FROM {t} WHERE {c} IS NOT NULL) GROUP BY u ORDER BY n DESC, u LIMIT 50",
        [UNIT_PATTERN],
    ).fetchall()
    total = sum(int(n) for _, n in rows)
    with_unit: list[dict[str, Any]] = [{"unit": str(u), "count": int(n)} for u, n in rows if u]
    if not total or not with_unit:
        return None
    return {"share": sum(u["count"] for u in with_unit) / total, "values": with_unit[:10]}


def _categories(
    con: duckdb.DuckDBPyConnection, t: str, c: str, non_null: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    top = [
        {"value": v, "count": n, "share": n / non_null}
        for v, n in con.execute(
            # The subquery exposes only `v`, so a data column named v or n cannot shadow
            # the aliases in GROUP BY / ORDER BY.
            f"SELECT v, count(*) AS n FROM (SELECT {c}::VARCHAR AS v FROM {t} "
            f"WHERE {c} IS NOT NULL) GROUP BY v ORDER BY n DESC, v LIMIT {TOP_VALUES}"
        ).fetchall()
    ]
    rare, largest, smallest = _one(
        con,
        f"SELECT count_if(n < ?), max(n), min(n) FROM "
        f"(SELECT count(*) AS n FROM {t} WHERE {c} IS NOT NULL GROUP BY {c})",
        [RARE_CATEGORY_SHARE * non_null],
    )
    return top, {
        "rare_categories": rare,
        "imbalance_ratio": largest / smallest,
        "top_share": largest / non_null,
    }


def _text(con: duckdb.DuckDBPyConnection, t: str, c: str) -> dict[str, Any]:
    min_len, avg_len, max_len, blank, avg_words = _one(
        con,
        f"""
        SELECT min(length({c})), avg(length({c})), max(length({c})),
               count_if(trim({c}) = ''),
               avg(len(string_split(regexp_replace(trim({c}), '\\s+', ' ', 'g'), ' ')))
        FROM {t} WHERE {c} IS NOT NULL
        """,
    )
    samples = [
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT {c} FROM {t} WHERE {c} IS NOT NULL AND trim({c}) <> '' "
            f"LIMIT {SAMPLE_VALUES}"
        ).fetchall()
    ]
    return {
        "min_length": min_len,
        "avg_length": avg_len,
        "max_length": max_len,
        "blank": blank,
        "avg_words": avg_words,
        "samples": samples,
        "units": _units(con, t, c),
    }


# Period used for "counts per period", from finest to coarsest.
PERIODS = ["day", "week", "month", "quarter", "year"]


def _datetime(con: duckdb.DuckDBPyConnection, t: str, c: str, physical: str) -> dict[str, Any]:
    lo, hi, has_time = _one(
        con,
        f"SELECT min({c}), max({c}), "
        + (
            f"count_if({c}::TIME <> TIME '00:00:00') > 0"
            if physical.upper().startswith("TIMESTAMP")
            else "false"
        )
        + f" FROM {t}",
    )
    gap_row = con.execute(
        f"""
        SELECT gap FROM (
            SELECT date_diff('day', lag(d) OVER (ORDER BY d), d) AS gap
            FROM (SELECT DISTINCT {c}::DATE AS d FROM {t} WHERE {c} IS NOT NULL)
        ) WHERE gap IS NOT NULL GROUP BY gap ORDER BY count(*) DESC, gap LIMIT 1
        """
    ).fetchone()
    gap = int(gap_row[0]) if gap_row else None
    granularity = _granularity(gap, has_time)

    span_days = (hi.date() if hasattr(hi, "date") else hi) - (
        lo.date() if hasattr(lo, "date") else lo
    )
    period = _period(span_days.days, granularity)
    counts = _period_counts(con, t, c, period)
    while len(counts) > MAX_PERIODS and period != "year":
        period = PERIODS[PERIODS.index(period) + 1]
        counts = _period_counts(con, t, c, period)

    return {
        "min": lo.isoformat(),
        "max": hi.isoformat(),
        "granularity": granularity,
        "period": period,
        "counts": counts,
        "empty_periods": sum(1 for p in counts if p["count"] == 0),
    }


def _granularity(gap_days: int | None, has_time: bool) -> str:
    if has_time:
        return "sub-daily"
    if gap_days is None:
        return "single date"
    if gap_days == 1:
        return "daily"
    if gap_days == 7:
        return "weekly"
    if 28 <= gap_days <= 31:
        return "monthly"
    if 89 <= gap_days <= 92:
        return "quarterly"
    if gap_days in (365, 366):
        return "yearly"
    return f"irregular (~{gap_days} days)"


def _period(span_days: int, granularity: str) -> str:
    by_span = "day" if span_days <= 92 else "week" if span_days <= 731 else "month"
    if span_days > 20 * 366:
        by_span = "year"
    # Never count at a finer period than the data has, or every gap looks like missing data.
    by_granularity = {"weekly": "week", "monthly": "month", "quarterly": "quarter"}.get(
        granularity, "year" if granularity == "yearly" else "day"
    )
    return max(by_span, by_granularity, key=PERIODS.index)


def _period_counts(
    con: duckdb.DuckDBPyConnection, t: str, c: str, period: str
) -> list[dict[str, Any]]:
    rows = con.execute(
        f"""
        WITH counts AS (
            SELECT p, count(*) AS n FROM (
                SELECT date_trunc('{period}', {c})::DATE AS p FROM {t} WHERE {c} IS NOT NULL
            ) GROUP BY p
        ),
        bounds AS (SELECT min(p) AS lo, max(p) AS hi FROM counts)
        SELECT s.p::DATE AS p, coalesce(counts.n, 0)
        FROM bounds, generate_series(bounds.lo, bounds.hi, INTERVAL 1 {period}) AS s(p)
        LEFT JOIN counts ON counts.p = s.p::DATE
        ORDER BY p
        """
    ).fetchall()
    return [{"period": p.isoformat(), "count": int(n)} for p, n in rows]


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    row = con.execute(sql, params or []).fetchone()
    assert row is not None
    return row


def _clean(value: Any) -> Any:
    """Make the profile JSON-safe: NaN/inf become None, tuples become lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if hasattr(value, "is_finite"):  # Decimal
        return float(value) if value.is_finite() else None
    return value
