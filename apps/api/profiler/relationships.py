"""Relationships between columns of one table: associations, near-duplicate columns, and
missing-data patterns.

Associations are computed on a deterministic sample of at most SAMPLE_ROWS rows; the sample
size is reported with every result. Near-duplicate checks run on the full table.
"""

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import duckdb
import numpy as np
from numpy.typing import NDArray
from scipy.stats import chi2_contingency, rankdata

from api.ingest.names import quote
from api.profiler.columns import ColumnLike

SAMPLE_ROWS = 50_000
MAX_COLUMNS_PER_KIND = 25
MAX_CATEGORIES = 50
MIN_PAIR_ROWS = 20
MIN_GROUP_ROWS = 20
KEEP_PAIRS = 50
MIN_REPORTED_ASSOCIATION = 0.1

# Thresholds for warnings
NEAR_PERFECT = {"spearman": 0.98, "cramers_v": 0.95, "eta": 0.95}
DUPLICATE_SHARE = 0.98
MAX_DUPLICATE_CHECKS = 200
CO_MISSING_PHI = 0.5
DEPENDENCY_V = 0.2
DEPENDENCY_SMD = 0.5
MISSING_RANGE = (0.01, 0.99)

NUMERIC_TYPES = {"numeric"}
CATEGORY_TYPES = {"categorical", "boolean"}

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


@dataclass
class Sample:
    rows: int
    numeric: dict[str, FloatArray] = field(default_factory=dict)
    codes: dict[str, IntArray] = field(default_factory=dict)  # -1 means missing
    labels: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, NDArray[np.bool_]] = field(default_factory=dict)
    truncated: dict[str, int] = field(default_factory=dict)  # kind -> columns left out


def analyse(
    con: duckdb.DuckDBPyConnection,
    table: str,
    row_count: int,
    columns: list[tuple[ColumnLike, dict[str, Any]]],
) -> dict[str, Any]:
    """Return {"sample_rows", "associations", "duplicates", "missingness", "truncated"}."""
    sample = draw_sample(con, table, row_count, columns)
    names = {c.name: c.original_name for c, _ in columns}
    duplicates = near_duplicates(con, table, row_count, columns)
    duplicate_pairs = {frozenset((d["a"], d["b"])) for d in duplicates}

    associations = [
        a
        for a in pairwise_associations(sample)
        if frozenset((a["a"], a["b"])) not in duplicate_pairs
    ]
    return {
        "sample_rows": sample.rows,
        "associations": associations,
        "duplicates": duplicates,
        "missingness": {
            "co_missing": co_missing(sample),
            "dependencies": missing_dependencies(sample, names),
        },
        "truncated": sample.truncated,
    }


def draw_sample(
    con: duckdb.DuckDBPyConnection,
    table: str,
    row_count: int,
    columns: list[tuple[ColumnLike, dict[str, Any]]],
) -> Sample:
    numeric = [c for c, p in columns if p["semantic_type"] in NUMERIC_TYPES]
    categorical = [
        c
        for c, p in columns
        if p["semantic_type"] in CATEGORY_TYPES and p["distinct"] <= MAX_CATEGORIES
    ]
    with_missing = [
        c for c, p in columns if MISSING_RANGE[0] <= p["missing_pct"] <= MISSING_RANGE[1]
    ]
    truncated = {
        kind: len(cols) - MAX_COLUMNS_PER_KIND
        for kind, cols in (
            ("numeric", numeric),
            ("categorical", categorical),
            ("missing", with_missing),
        )
        if len(cols) > MAX_COLUMNS_PER_KIND
    }
    numeric = numeric[:MAX_COLUMNS_PER_KIND]
    categorical = categorical[:MAX_COLUMNS_PER_KIND]
    with_missing = with_missing[:MAX_COLUMNS_PER_KIND]

    needed = list(dict.fromkeys(c.name for c in [*numeric, *categorical, *with_missing]))
    sample = Sample(rows=0, truncated=truncated)
    if not needed or row_count == 0:
        return sample

    # Deterministic sample: the same file always gives the same numbers.
    limit = f"ORDER BY hash(rowid) LIMIT {SAMPLE_ROWS}" if row_count > SAMPLE_ROWS else ""
    exprs: list[str] = []
    for c in numeric:
        exprs.append(f"coalesce({quote(c.name)}::DOUBLE, 'NaN'::DOUBLE) AS {quote('n_' + c.name)}")
    for c in categorical:
        exprs.append(f"{quote(c.name)}::VARCHAR AS {quote('c_' + c.name)}")
    for c in with_missing:
        exprs.append(f"{quote(c.name)} IS NULL AS {quote('m_' + c.name)}")
    data = con.execute(f"SELECT {', '.join(exprs)} FROM {quote(table)} {limit}").fetchnumpy()

    sample.rows = len(next(iter(data.values())))
    for c in numeric:
        sample.numeric[c.name] = np.asarray(data["n_" + c.name], dtype=np.float64)
    for c in categorical:
        raw = data["c_" + c.name]
        mask = np.ma.getmaskarray(raw)
        values = np.asarray(np.ma.filled(raw.astype(object), ""), dtype=object)
        labels, inverse = np.unique(values[~mask].astype(str), return_inverse=True)
        codes = np.full(sample.rows, -1, dtype=np.int64)
        codes[~mask] = inverse
        sample.codes[c.name] = codes
        sample.labels[c.name] = [str(v) for v in labels]
    for c in with_missing:
        sample.missing[c.name] = np.asarray(data["m_" + c.name], dtype=bool)
    return sample


# Association measures ---------------------------------------------------------------------


def spearman(x: FloatArray, y: FloatArray) -> tuple[float, int] | None:
    mask = ~np.isnan(x) & ~np.isnan(y)
    n = int(mask.sum())
    if n < MIN_PAIR_ROWS:
        return None
    rx, ry = rankdata(x[mask]), rankdata(y[mask])
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1]), n


def cramers_v(a: IntArray, b: IntArray) -> tuple[float, int] | None:
    mask = (a >= 0) & (b >= 0)
    n = int(mask.sum())
    if n < MIN_PAIR_ROWS:
        return None
    _, ia = np.unique(a[mask], return_inverse=True)
    _, ib = np.unique(b[mask], return_inverse=True)
    ka, kb = int(ia.max()) + 1, int(ib.max()) + 1
    if ka < 2 or kb < 2:
        return None
    table = np.bincount(ia * kb + ib, minlength=ka * kb).reshape(ka, kb)
    chi2 = float(chi2_contingency(table, correction=False)[0])
    return float(np.sqrt(chi2 / (n * (min(ka, kb) - 1)))), n


def correlation_ratio(codes: IntArray, x: FloatArray) -> tuple[float, int] | None:
    """Eta: share of the numeric column's variance explained by the categories (square-rooted)."""
    mask = (codes >= 0) & ~np.isnan(x)
    n = int(mask.sum())
    if n < MIN_PAIR_ROWS:
        return None
    _, groups = np.unique(codes[mask], return_inverse=True)
    values = x[mask]
    if groups.max() < 1:
        return None
    counts = np.bincount(groups)
    means = np.bincount(groups, weights=values) / counts
    ss_total = float(((values - values.mean()) ** 2).sum())
    if ss_total == 0:
        return None
    ss_between = float((counts * (means - values.mean()) ** 2).sum())
    return float(np.sqrt(ss_between / ss_total)), n


def pairwise_associations(sample: Sample) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(a: str, b: str, measure: str, result: tuple[float, int] | None) -> None:
        if result is not None and abs(result[0]) >= MIN_REPORTED_ASSOCIATION:
            out.append({"a": a, "b": b, "measure": measure, "value": result[0], "n": result[1]})

    for a, b in combinations(sample.numeric, 2):
        add(a, b, "spearman", spearman(sample.numeric[a], sample.numeric[b]))
    for a, b in combinations(sample.codes, 2):
        add(a, b, "cramers_v", cramers_v(sample.codes[a], sample.codes[b]))
    for c in sample.codes:
        for x in sample.numeric:
            if c != x:
                add(c, x, "eta", correlation_ratio(sample.codes[c], sample.numeric[x]))

    out.sort(key=lambda r: -abs(r["value"]))
    return out[:KEEP_PAIRS]


# Near-duplicate columns (full table) --------------------------------------------------------


def near_duplicates(
    con: duckdb.DuckDBPyConnection,
    table: str,
    row_count: int,
    columns: list[tuple[ColumnLike, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Pairs of columns whose values are equal in at least DUPLICATE_SHARE of rows."""
    if row_count == 0:
        return []
    usable = [(c, p) for c, p in columns if p["semantic_type"] != "constant" and p["non_null"]]
    candidates = [
        (a, b)
        for (a, pa), (b, pb) in combinations(usable, 2)
        # Equal columns have (nearly) equal distinct and missing counts.
        if min(pa["distinct"], pb["distinct"]) >= 0.95 * max(pa["distinct"], pb["distinct"])
        and abs(pa["missing"] - pb["missing"]) <= (1 - DUPLICATE_SHARE) * row_count
    ][:MAX_DUPLICATE_CHECKS]

    out: list[dict[str, Any]] = []
    for a, b in candidates:
        row = con.execute(
            f"SELECT count_if({quote(a.name)}::VARCHAR IS NOT DISTINCT FROM "
            f"{quote(b.name)}::VARCHAR) FROM {quote(table)}"
        ).fetchone()
        same = int(row[0]) if row else 0
        if same / row_count >= DUPLICATE_SHARE:
            out.append({"a": a.name, "b": b.name, "same_rows": same, "share": same / row_count})
    return out


# Missing-data patterns ----------------------------------------------------------------------


def co_missing(sample: Sample) -> list[dict[str, Any]]:
    """Pairs of columns that tend to be missing in the same rows (phi coefficient)."""
    out: list[dict[str, Any]] = []
    for a, b in combinations(sample.missing, 2):
        ma, mb = sample.missing[a], sample.missing[b]
        if ma.std() == 0 or mb.std() == 0:
            continue
        phi = float(np.corrcoef(ma, mb)[0, 1])
        if phi >= CO_MISSING_PHI:
            out.append({"a": a, "b": b, "phi": phi, "both_missing": int((ma & mb).sum())})
    out.sort(key=lambda r: -r["phi"])
    return out


def missing_dependencies(sample: Sample, names: dict[str, str]) -> list[dict[str, Any]]:
    """Columns whose missingness differs across the values of another column.

    For a categorical column: Cramér's V between "is missing" and the category, with the
    categories that have the highest and lowest missing rate. For a numeric column: the
    standardised mean difference between rows where the first column is missing and present.
    """
    out: list[dict[str, Any]] = []
    for col, miss in sample.missing.items():
        indicator = miss.astype(np.int64)
        for other, codes in sample.codes.items():
            if other == col:
                continue
            result = cramers_v(indicator, codes)
            if result is None or result[0] < DEPENDENCY_V:
                continue
            rates = []
            for code, label in enumerate(sample.labels[other]):
                in_group = codes == code
                size = int(in_group.sum())
                if size >= MIN_GROUP_ROWS:
                    rates.append((float(miss[in_group].mean()), label, size))
            if len(rates) < 2:
                continue
            rates.sort()
            out.append(
                {
                    "column": col,
                    "by": other,
                    "kind": "categorical",
                    "strength": result[0],
                    "measure": "cramers_v",
                    "highest": {"value": rates[-1][1], "rate": rates[-1][0], "rows": rates[-1][2]},
                    "lowest": {"value": rates[0][1], "rate": rates[0][0], "rows": rates[0][2]},
                }
            )
        for other, values in sample.numeric.items():
            if other == col:
                continue
            present = ~np.isnan(values)
            when_missing, when_present = values[present & miss], values[present & ~miss]
            if len(when_missing) < MIN_GROUP_ROWS or len(when_present) < MIN_GROUP_ROWS:
                continue
            pooled = np.sqrt((when_missing.var(ddof=1) + when_present.var(ddof=1)) / 2)
            if pooled == 0:
                continue
            smd = float((when_missing.mean() - when_present.mean()) / pooled)
            if abs(smd) >= DEPENDENCY_SMD:
                out.append(
                    {
                        "column": col,
                        "by": other,
                        "kind": "numeric",
                        "strength": abs(smd),
                        "measure": "smd",
                        "smd": smd,
                        "mean_when_missing": float(when_missing.mean()),
                        "mean_when_present": float(when_present.mean()),
                    }
                )
    out.sort(key=lambda r: -r["strength"])
    return out
