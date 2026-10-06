"""Effect sizes reported next to every test, so results are not judged by p-value alone."""

import math


def cliffs_delta(u_a: float, n_a: int, n_b: int) -> float:
    """Cliff's delta from the Mann-Whitney U of group a: P(a > b) - P(a < b), in [-1, 1]."""
    return 2 * u_a / (n_a * n_b) - 1


def epsilon_squared(h: float, n: int) -> float:
    """Epsilon squared for Kruskal-Wallis H: H / (n - 1), in [0, 1]."""
    return h / (n - 1) if n > 1 else 0.0


def cramers_v(chi2: float, n: int, rows: int, cols: int) -> float:
    """Cramér's V without bias correction, as in the profiler, in [0, 1]."""
    k = min(rows, cols) - 1
    return math.sqrt(chi2 / (n * k)) if n and k > 0 else 0.0


def magnitude(measure: str, value: float) -> str:
    """Conventional labels: Cohen (1988) for rho and V, Romano et al. (2006) for delta."""
    v = abs(value)
    cuts = {
        "rho": (0.1, 0.3, 0.5),
        "cramers_v": (0.1, 0.3, 0.5),
        "cliffs_delta": (0.147, 0.33, 0.474),
        "epsilon_squared": (0.01, 0.08, 0.26),
        "kendall_tau": (0.1, 0.3, 0.5),
    }[measure]
    if v < cuts[0]:
        return "negligible"
    if v < cuts[1]:
        return "small"
    if v < cuts[2]:
        return "medium"
    return "large"
