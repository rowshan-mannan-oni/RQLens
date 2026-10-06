"""Associations, missing-data patterns, unit checks and joins.

Statistics are checked against values worked out by hand or against scipy; the CSV cases plant
one known problem per column.
"""

from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pytest
from scipy.stats import spearmanr

from api.ingest.loader import load_csv
from api.profiler.joins import JoinColumn, JoinTable, find_joins, name_match
from api.profiler.relationships import correlation_ratio, cramers_v, spearman
from api.profiler.tables import DatasetProfile, profile_table


def test_cramers_v_by_hand() -> None:
    # Table [[10, 20], [30, 40]]: chi2 = 4/12 + 4/18 + 4/28 + 4/42 = 0.7937, V = sqrt(chi2 / 100)
    a = np.array([0] * 30 + [1] * 70)
    b = np.array([0] * 10 + [1] * 20 + [0] * 30 + [1] * 40)
    result = cramers_v(a, b)
    assert result is not None
    assert result[0] == pytest.approx(0.0891, abs=1e-4)
    assert result[1] == 100


def test_correlation_ratio_by_hand() -> None:
    # Groups with means 2 and 5; SS_between = 24 * 1.5^2 = 54, SS_total = 70.
    codes = np.array([0, 0, 0, 1, 1, 1] * 4)
    x = np.array([1.0, 2, 3, 4, 5, 6] * 4)
    result = correlation_ratio(codes, x)
    assert result is not None
    assert result[0] == pytest.approx(np.sqrt(54 / 70))


def test_spearman_matches_scipy_with_missing_values() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    y = x**3 + rng.normal(scale=0.5, size=200)
    x[::7] = np.nan
    y[::11] = np.nan
    mask = ~np.isnan(x) & ~np.isnan(y)
    result = spearman(x, y)
    assert result is not None
    assert result[0] == pytest.approx(spearmanr(x[mask], y[mask]).statistic)
    assert result[1] == int(mask.sum())


def planted_csv() -> str:
    lines = ["id,grp,income,income_copy,outcome,outcome_label,weight,height"]
    for i in range(400):
        grp = "A" if i % 2 == 0 else "B"
        # Income is missing for half of group A and never for group B.
        income = "" if grp == "A" and i % 4 == 0 else str(1000 + i)
        outcome = i % 3
        label = ["low", "mid", "high"][outcome]
        # Weight switches from kg to lb at row 201.
        kg = 70 + i % 10
        weight = kg if i < 200 else round(kg * 2.2046, 1)
        height = "67 in" if i % 5 == 0 else "170 cm"
        lines.append(f"{i},{grp},{income},{income},{outcome},{label},{weight},{height}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def planted(tmp_path: Path) -> DatasetProfile:
    path = tmp_path / "planted.csv"
    path.write_text(planted_csv(), encoding="utf-8")
    con = duckdb.connect()
    return profile_table(con, load_csv(con, path, "planted"))


def warning_for(result: DatasetProfile, code: str) -> list[dict[str, Any]]:
    return [dict(w) for w in result.warnings if w["code"] == code]


def test_near_duplicate_columns(planted: DatasetProfile) -> None:
    (w,) = warning_for(planted, "near_duplicate_columns")
    assert {w["details"]["a"], w["details"]["b"]} == {"income", "income_copy"}
    assert w["details"]["share"] == 1.0


def test_leaked_label(planted: DatasetProfile) -> None:
    pairs = [
        {w["details"]["a"], w["details"]["b"]}
        for w in warning_for(planted, "near_perfect_association")
    ]
    assert {"outcome", "outcome_label"} in pairs


def test_missingness_depends_on_group(planted: DatasetProfile) -> None:
    deps = {w["column"]: w["details"] for w in warning_for(planted, "missing_depends")}
    income = deps["income"]
    assert income["by"] == "grp"
    assert income["highest"] == {"value": "A", "rate": 0.5, "rows": 200}
    assert income["lowest"] == {"value": "B", "rate": 0.0, "rows": 200}
    # phi for the 2x2 table [[100, 100], [0, 200]] = 20000 / sqrt(200*200*100*300)
    assert income["strength"] == pytest.approx(20000 / np.sqrt(200 * 200 * 100 * 300))

    co = planted.table["relationships"]["missingness"]["co_missing"]
    assert co[0]["phi"] == pytest.approx(1.0)
    assert {co[0]["a"], co[0]["b"]} == {"income", "income_copy"}


def test_unit_shift(planted: DatasetProfile) -> None:
    (w,) = warning_for(planted, "unit_shift")
    assert w["column"] == "weight"
    assert w["details"]["from_row"] == 201
    assert w["details"]["ratio"] == pytest.approx(2.2, rel=0.01)


def test_mixed_units(planted: DatasetProfile) -> None:
    (w,) = warning_for(planted, "mixed_units")
    assert w["column"] == "height"
    assert {u["unit"]: u["count"] for u in w["details"]["values"]} == {"cm": 320, "in": 80}


def test_no_false_alarms_on_clean_columns(planted: DatasetProfile) -> None:
    flagged = {w["column"] for w in planted.warnings}
    assert "grp" not in flagged
    assert "id" not in flagged or all(
        w["code"] == "identifier" for w in planted.warnings if w["column"] == "id"
    )


def test_join_between_tables(tmp_path: Path) -> None:
    con = duckdb.connect()
    (tmp_path / "customers.csv").write_text(
        "id,name\n" + "\n".join(f"{i},Customer {i}" for i in range(1, 51)) + "\n"
    )
    (tmp_path / "orders.csv").write_text(
        "order_id,customer_id,amount\n"
        + "\n".join(f"{n},{n % 40 + 1},{n * 3}" for n in range(1, 201))
        + "\n"
    )

    def table(dataset_id: int, name: str) -> JoinTable:
        profile = profile_table(con, load_csv(con, tmp_path / f"{name}.csv", name))
        return JoinTable(
            dataset_id=dataset_id,
            table_name=name,
            columns=tuple(
                JoinColumn(
                    name=r.column.name,
                    physical_type=r.column.physical_type,
                    semantic_type=r.profile["semantic_type"],
                    distinct=r.profile["distinct"],
                    uniqueness=r.profile["uniqueness"],
                )
                for r in profile.columns
            ),
        )

    customers, orders = table(1, "customers"), table(2, "orders")
    joins = find_joins(con, orders, [customers])
    top = joins[0]
    assert (top["left_column"], top["right_column"]) == ("customer_id", "id")
    assert top["name_match"] is True
    assert top["cardinality"] == "many-to-one"
    assert top["shared_values"] == 40
    assert top["left_coverage"] == 1.0  # every customer_id exists in customers
    assert top["right_coverage"] == pytest.approx(0.8)  # 40 of 50 customers have orders


def test_generic_names_are_not_a_join() -> None:
    def col(name: str) -> JoinColumn:
        return JoinColumn(name, "BIGINT", "identifier", distinct=50, uniqueness=1.0)

    customers = JoinTable(1, "customers", (col("id"),))
    survey = JoinTable(2, "survey", (col("id"),))
    orders = JoinTable(3, "orders", (col("customer_id"),))
    assert not name_match(col("id"), customers, col("id"), survey)
    assert name_match(col("customer_id"), orders, col("id"), customers)
    assert name_match(col("patient_code"), orders, col("patient_code"), survey)
