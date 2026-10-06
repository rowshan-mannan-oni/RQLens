"""Statistics library against scipy and hand-calculated values."""

import math

import pytest
from scipy import stats

from api.stats.library import StatTestError, run_test


def test_spearman_drops_missing_pairs() -> None:
    x = [1, 2, 3, 4, 5, 6, None]
    y = [2, 1, 4, 3, 6, 5, 9]
    r = run_test("spearman", x, y)
    rho, p = stats.spearmanr(x[:6], y[:6])
    assert r.n == 6
    assert r.statistic == pytest.approx(rho)
    assert r.p_value == pytest.approx(p)


def test_mann_whitney_effect_size_by_hand() -> None:
    # Every value in group a is larger than every value in b: U = 3 * 3 = 9, r = 1.
    values = [10, 11, 12, 1, 2, 3]
    groups = ["a", "a", "a", "b", "b", "b"]
    r = run_test("mann_whitney", values, groups)
    assert r.statistic == 9
    assert r.effect_size == pytest.approx(1.0)
    assert [g["group"] for g in r.groups] == ["a", "b"]
    assert r.groups[0]["median"] == 11


def test_mann_whitney_needs_two_groups() -> None:
    with pytest.raises(StatTestError, match="exactly 2 groups"):
        run_test("mann_whitney", [1, 2, 3, 4, 5, 6], ["a", "b", "c", "a", "b", "c"])


def test_kruskal_matches_scipy() -> None:
    a, b, c = [1, 2, 3, 4], [3, 4, 5, 6], [7, 8, 9, 10]
    r = run_test("kruskal_wallis", a + b + c, ["a"] * 4 + ["b"] * 4 + ["c"] * 4)
    h, p = stats.kruskal(a, b, c)
    assert r.statistic == pytest.approx(h)
    assert r.p_value == pytest.approx(p)
    assert r.effect_size == pytest.approx(h / 11)


def test_chi_square_cramers_v_by_hand() -> None:
    # Perfect association in a 2x2 table: chi2 = n, V = 1.
    x = ["a"] * 10 + ["b"] * 10
    y = ["u"] * 10 + ["v"] * 10
    r = run_test("chi_square", x, y)
    assert r.statistic == pytest.approx(20)
    assert r.effect_size == pytest.approx(1.0)
    assert r.n == 20


def test_trend_on_iso_dates() -> None:
    days = [f"2024-01-{d:02d}" for d in range(1, 11)]
    r = run_test("trend", days, list(range(10)))
    assert r.statistic == pytest.approx(1.0)
    assert r.p_value < 0.001


def test_errors() -> None:
    with pytest.raises(StatTestError, match="Unknown test"):
        run_test("t_test", [1], [1])
    with pytest.raises(StatTestError, match="Too few"):
        run_test("spearman", [1, 2], [1, 2])
    with pytest.raises(StatTestError, match="numeric"):
        run_test("spearman", ["a", "b", "c", "d", "e"], [1, 2, 3, 4, 5])


def test_json_rounds_and_drops_nan() -> None:
    r = run_test("spearman", [1, 2, 3, 4, 5], [5, 6, 7, 8, 7])
    out = r.to_json()
    assert out["test"] == "spearman"
    assert all(v is None or not isinstance(v, float) or math.isfinite(v) for v in out.values())
