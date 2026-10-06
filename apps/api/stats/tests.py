"""The fixed library of statistical tests the agent and the insight runner may use.

Each test takes the two-column rows of a query result. Generated code never runs; the model can
only pick a test by name and supply the query that feeds it.

| Test           | Columns            | Effect size     |
|----------------|--------------------|-----------------|
| spearman       | (x, y) numeric     | rho             |
| mann_whitney   | (group, value)     | Cliff's delta   |
| kruskal        | (group, value)     | epsilon squared |
| chi_square     | (a, b) categorical | Cramér's V      |
| trend          | (time, value)      | Kendall's tau   |
"""

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import stats

from api.stats.effect_sizes import cliffs_delta, cramers_v, epsilon_squared, magnitude

TESTS = ("spearman", "mann_whitney", "kruskal", "chi_square", "trend")
COLUMN_LAYOUT = {
    "spearman": "two numeric columns (x, y)",
    "mann_whitney": "a group label and a numeric value (group, value), with exactly two groups",
    "kruskal": "a group label and a numeric value (group, value), with two or more groups",
    "chi_square": "two categorical columns (a, b)",
    "trend": "a time or ordered numeric column and a numeric value (time, value)",
}
MIN_ROWS = 3
MIN_GROUP_ROWS = 2
MAX_GROUPS = 50
MAX_CATEGORIES = 50
SMALL_EXPECTED = 5


class StatTestError(ValueError):
    """The data does not fit the test. The message is safe to show to the model."""


def run_test(test: str, rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """Run `test` on query rows; rows with a missing value in either column are dropped."""
    if test not in TESTS:
        raise StatTestError(f"Unknown test '{test}'. Available: {', '.join(TESTS)}.")
    if any(len(r) != 2 for r in rows):
        raise StatTestError(f"{test} needs a query returning {COLUMN_LAYOUT[test]}.")
    pairs = [(a, b) for a, b in rows if a is not None and b is not None]
    dropped = len(rows) - len(pairs)
    if len(pairs) < MIN_ROWS:
        raise StatTestError(f"Only {len(pairs)} complete rows; at least {MIN_ROWS} are needed.")

    result: dict[str, Any] = {"test": test, "n": len(pairs), "rows_dropped_missing": dropped}
    result.update(
        {
            "spearman": _spearman,
            "mann_whitney": _mann_whitney,
            "kruskal": _kruskal,
            "chi_square": _chi_square,
            "trend": _trend,
        }[test](pairs)
    )
    effect = result.get("effect_size")
    if effect is not None:
        effect["magnitude"] = magnitude(effect["measure"], effect["value"])
    cleaned: dict[str, Any] = _clean(result)
    return cleaned


def _numbers(values: Sequence[Any], label: str) -> np.ndarray[Any, np.dtype[np.float64]]:
    try:
        out = np.array([float(v) for v in values], dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise StatTestError(f"The {label} column must be numeric.") from exc
    if not np.isfinite(out).all():
        raise StatTestError(f"The {label} column contains infinite values.")
    return out


def _spearman(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    x = _numbers([a for a, _ in pairs], "first")
    y = _numbers([b for _, b in pairs], "second")
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        raise StatTestError("One column is constant, so no correlation can be computed.")
    rho, p = stats.spearmanr(x, y)
    return {
        "statistic": {"name": "rho", "value": float(rho)},
        "p_value": float(p),
        "effect_size": {"measure": "rho", "value": float(rho)},
    }


def _groups(pairs: list[tuple[Any, Any]]) -> dict[str, np.ndarray[Any, np.dtype[np.float64]]]:
    raw: dict[str, list[Any]] = defaultdict(list)
    for g, v in pairs:
        raw[str(g)].append(v)
    if len(raw) > MAX_GROUPS:
        raise StatTestError(f"{len(raw)} groups; at most {MAX_GROUPS} are allowed.")
    small = [g for g, vs in raw.items() if len(vs) < MIN_GROUP_ROWS]
    if small:
        raise StatTestError(
            f"Groups with fewer than {MIN_GROUP_ROWS} rows: {', '.join(small[:5])}. "
            "Filter them out or merge them."
        )
    return {g: _numbers(vs, "value") for g, vs in raw.items()}


def _describe_groups(
    groups: dict[str, np.ndarray[Any, np.dtype[np.float64]]],
) -> list[dict[str, Any]]:
    return [
        {"group": g, "n": len(v), "median": float(np.median(v)), "mean": float(np.mean(v))}
        for g, v in sorted(groups.items())
    ]


def _mann_whitney(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    groups = _groups(pairs)
    if len(groups) != 2:
        raise StatTestError(
            f"mann_whitney needs exactly 2 groups, found {len(groups)}; use kruskal instead."
        )
    (name_a, a), (name_b, b) = sorted(groups.items())
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    delta = cliffs_delta(float(u), len(a), len(b))
    return {
        "statistic": {"name": "U", "value": float(u)},
        "p_value": float(p),
        "effect_size": {"measure": "cliffs_delta", "value": delta},
        "groups": _describe_groups(groups),
        "notes": [
            f"A positive delta means values in '{name_a}' tend to be higher than '{name_b}'."
        ],
    }


def _kruskal(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    groups = _groups(pairs)
    if len(groups) < 2:
        raise StatTestError("kruskal needs at least 2 groups.")
    values = list(groups.values())
    if np.ptp(np.concatenate(values)) == 0:
        raise StatTestError("All values are identical, so groups cannot differ.")
    h, p = stats.kruskal(*values)
    n = sum(len(v) for v in values)
    return {
        "statistic": {"name": "H", "value": float(h)},
        "p_value": float(p),
        "effect_size": {"measure": "epsilon_squared", "value": epsilon_squared(float(h), n)},
        "groups": _describe_groups(groups),
    }


def _chi_square(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    a_labels = sorted({str(a) for a, _ in pairs})
    b_labels = sorted({str(b) for _, b in pairs})
    if len(a_labels) > MAX_CATEGORIES or len(b_labels) > MAX_CATEGORIES:
        raise StatTestError(f"At most {MAX_CATEGORIES} categories per column are allowed.")
    if len(a_labels) < 2 or len(b_labels) < 2:
        raise StatTestError("Each column needs at least 2 categories.")
    ai = {v: i for i, v in enumerate(a_labels)}
    bi = {v: i for i, v in enumerate(b_labels)}
    table = np.zeros((len(a_labels), len(b_labels)), dtype=np.int64)
    for a, b in pairs:
        table[ai[str(a)], bi[str(b)]] += 1
    chi2, p, dof, expected = stats.chi2_contingency(table, correction=False)
    notes = []
    small = float((expected < SMALL_EXPECTED).mean())
    if small > 0.2:
        notes.append(
            f"{small:.0%} of cells have an expected count below {SMALL_EXPECTED}; "
            "the p-value may be unreliable."
        )
    return {
        "statistic": {"name": "chi2", "value": float(chi2), "dof": int(dof)},
        "p_value": float(p),
        "effect_size": {
            "measure": "cramers_v",
            "value": cramers_v(float(chi2), len(pairs), *table.shape),
        },
        "table": {"rows": a_labels, "columns": b_labels, "counts": table.tolist()},
        "notes": notes,
    }


def _time_value(v: Any) -> tuple[float, bool]:
    """A time as days since 1970-01-01 (dates), or the number itself. Second: is a date."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        return float(v), False
    if isinstance(v, dt.datetime | dt.date):
        d = v
    else:
        try:
            d = dt.datetime.fromisoformat(str(v))
        except ValueError as exc:
            raise StatTestError("The time column must hold dates or numbers.") from exc
    if not isinstance(d, dt.datetime):
        d = dt.datetime(d.year, d.month, d.day)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.UTC)
    return d.timestamp() / 86400, True


def _trend(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    times = [_time_value(t) for t, _ in pairs]
    x = np.array([t for t, _ in times], dtype=np.float64)
    is_date = any(d for _, d in times)
    y = _numbers([v for _, v in pairs], "value")
    if np.ptp(x) == 0:
        raise StatTestError("All rows share one time point, so there is no trend to test.")
    tau, p = stats.kendalltau(x, y)
    slope, _intercept, low, high = stats.theilslopes(y, x)
    unit = "per day" if is_date else "per unit of the time column"
    out: dict[str, Any] = {
        "statistic": {"name": "kendall_tau", "value": float(tau)},
        "p_value": float(p),
        "effect_size": {"measure": "kendall_tau", "value": float(tau)},
        "slope": {"value": float(slope), "unit": unit, "ci95": [float(low), float(high)]},
        "notes": ["Mann-Kendall style test (Kendall's tau against time) with Theil-Sen slope."],
    }
    if is_date:
        out["slope_per_year"] = float(slope) * 365.25
    return out


def _clean(value: Any) -> Any:
    """Make results JSON-safe: NaN and infinity become None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value
