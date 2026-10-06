"""The fixed library of statistical tests the agent (and later the insight runner) may use.

Each test takes plain value lists, drops missing values pairwise, and returns a TestResult
with the statistic, p-value, an effect size and the sample sizes. No generated code runs.
"""

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from scipy import stats

MIN_N = 5
MAX_GROUPS = 50
MAX_CATEGORIES = 50


class StatTestError(ValueError):
    """The data does not suit the test. The message is safe to show to the model."""


@dataclass
class TestResult:
    test: str
    statistic_name: str
    statistic: float
    p_value: float
    effect_size_name: str
    effect_size: float
    n: int
    groups: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {k: _round(v) for k, v in asdict(self).items()}


def _round(v: Any) -> Any:
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return float(f"{v:.6g}")
    if isinstance(v, list):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


def _is_missing(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _pairs(x: Sequence[Any], y: Sequence[Any]) -> list[tuple[Any, Any]]:
    return [(a, b) for a, b in zip(x, y, strict=True) if not _is_missing(a) and not _is_missing(b)]


def _numbers(values: Sequence[Any], column: str) -> np.ndarray:
    try:
        return np.asarray([float(v) for v in values], dtype=float)
    except (TypeError, ValueError) as exc:
        raise StatTestError(f"Column {column} must be numeric for this test.") from exc


def _need(n: int, minimum: int = MIN_N) -> None:
    if n < minimum:
        raise StatTestError(f"Too few complete rows ({n}); at least {minimum} are needed.")


def _by_group(values: Sequence[Any], groups: Sequence[Any]) -> dict[str, np.ndarray]:
    pairs = _pairs(values, groups)
    _need(len(pairs))
    nums = _numbers([p[0] for p in pairs], "value")
    out: dict[str, list[float]] = {}
    for v, g in zip(nums, (str(p[1]) for p in pairs), strict=True):
        out.setdefault(g, []).append(float(v))
    if len(out) > MAX_GROUPS:
        raise StatTestError(f"The group column has {len(out)} groups; the limit is {MAX_GROUPS}.")
    return {g: np.asarray(v) for g, v in sorted(out.items())}


def _group_summary(groups: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    return [
        {"group": g, "n": int(v.size), "median": float(np.median(v)), "mean": float(v.mean())}
        for g, v in groups.items()
    ]


def spearman(x: Sequence[Any], y: Sequence[Any]) -> TestResult:
    """Monotonic association between two numeric columns."""
    pairs = _pairs(x, y)
    _need(len(pairs))
    a = _numbers([p[0] for p in pairs], "x")
    b = _numbers([p[1] for p in pairs], "y")
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        raise StatTestError("One of the columns is constant; the correlation is undefined.")
    rho, p = stats.spearmanr(a, b)
    return TestResult("spearman", "rho", float(rho), float(p), "rho", float(rho), len(pairs))


def mann_whitney(values: Sequence[Any], groups: Sequence[Any]) -> TestResult:
    """Difference in distribution of a numeric column between exactly two groups."""
    by = _by_group(values, groups)
    if len(by) != 2:
        raise StatTestError(
            f"Mann-Whitney U needs exactly 2 groups; found {len(by)}. "
            "Use kruskal_wallis for more, or filter to two groups."
        )
    (_, a), (_, b) = by.items()
    if min(a.size, b.size) < 2:
        raise StatTestError("Each group needs at least 2 values.")
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    # Rank-biserial correlation: positive when the first group tends to be larger.
    r = 2 * float(u) / (a.size * b.size) - 1
    return TestResult(
        "mann_whitney", "U", float(u), float(p), "rank_biserial", r, int(a.size + b.size),
        _group_summary(by),
    )  # fmt: skip


def kruskal_wallis(values: Sequence[Any], groups: Sequence[Any]) -> TestResult:
    """Difference in distribution of a numeric column across two or more groups."""
    by = _by_group(values, groups)
    if len(by) < 2:
        raise StatTestError("Kruskal-Wallis needs at least 2 groups.")
    arrays = list(by.values())
    n = sum(a.size for a in arrays)
    h, p = stats.kruskal(*arrays)
    # Epsilon squared, H / (n - 1).
    eps = float(h) / (n - 1) if n > 1 else math.nan
    return TestResult(
        "kruskal_wallis", "H", float(h), float(p), "epsilon_squared", eps, n, _group_summary(by)
    )


def chi_square(x: Sequence[Any], y: Sequence[Any]) -> TestResult:
    """Independence of two categorical columns, with Cramér's V."""
    pairs = [(str(a), str(b)) for a, b in _pairs(x, y)]
    _need(len(pairs))
    rows = sorted({a for a, _ in pairs})
    cols = sorted({b for _, b in pairs})
    if len(rows) > MAX_CATEGORIES or len(cols) > MAX_CATEGORIES:
        raise StatTestError(f"Too many categories; the limit is {MAX_CATEGORIES} per column.")
    if len(rows) < 2 or len(cols) < 2:
        raise StatTestError("Each column needs at least 2 categories.")
    counts = Counter(pairs)
    table = np.asarray([[counts[(r, c)] for c in cols] for r in rows], dtype=float)
    chi2, p, dof, expected = stats.chi2_contingency(table, correction=False)
    n = int(table.sum())
    v = math.sqrt(float(chi2) / (n * (min(table.shape) - 1)))
    low = float((expected < 5).mean())
    note = (
        f"{low:.0%} of expected cell counts are below 5; the p-value may be unreliable."
        if low > 0.2
        else ""
    )
    return TestResult(
        "chi_square", f"chi2 (dof={int(dof)})", float(chi2), float(p), "cramers_v", v, n, note=note
    )


def trend(time: Sequence[Any], values: Sequence[Any]) -> TestResult:
    """Monotonic trend of a numeric column over time (Kendall's tau against time order).

    `time` may be numbers or ISO date strings.
    """
    pairs = _pairs(time, values)
    _need(len(pairs))
    keys = [_time_key(t) for t, _ in pairs]
    distinct = sorted(set(keys))
    if len(distinct) < 3:
        raise StatTestError("The time column needs at least 3 distinct values.")
    position = {k: i for i, k in enumerate(distinct)}
    v = _numbers([p[1] for p in pairs], "value")
    tau, p = stats.kendalltau([position[k] for k in keys], v)
    return TestResult("trend", "kendall_tau", float(tau), float(p), "tau", float(tau), len(pairs))


def _time_key(t: Any) -> float | str:
    if isinstance(t, int | float):
        return float(t)
    return str(t)  # ISO dates and timestamps sort correctly as text


TESTS: dict[str, tuple[Callable[[Sequence[Any], Sequence[Any]], TestResult], str]] = {
    "spearman": (spearman, "x and y: two numeric columns"),
    "mann_whitney": (mann_whitney, "x: numeric outcome, y: group column with exactly 2 groups"),
    "kruskal_wallis": (kruskal_wallis, "x: numeric outcome, y: group column (2 or more groups)"),
    "chi_square": (chi_square, "x and y: two categorical columns"),
    "trend": (trend, "x: date/time or ordered numeric column, y: numeric value"),
}


def run_test(name: str, x: Sequence[Any], y: Sequence[Any]) -> TestResult:
    if name not in TESTS:
        raise StatTestError(f"Unknown test {name!r}. Available: {', '.join(TESTS)}.")
    return TESTS[name][0](x, y)
