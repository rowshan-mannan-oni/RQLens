"""Combining tables (stack and join) and comparing several tables."""

import duckdb
import pytest

from api.ingest.combine import SourceTable, join_plan, run_combine, stack_plan
from api.profiler.compare import CompareColumn, CompareTable, compare


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE s2023 AS SELECT * FROM (VALUES (1, 30, 'A'), (2, 40, 'B')) t(id, age, grp)"
    )
    con.execute(
        "CREATE TABLE s2024 AS SELECT * FROM (VALUES (3, 35, 'A', 5)) t(id, age, grp, score)"
    )
    con.execute(
        "CREATE TABLE customers AS SELECT * FROM "
        "(VALUES (1, 'Ann', 'Paris'), (2, 'Bo', 'Lyon')) t(id, name, city)"
    )
    con.execute(
        "CREATE TABLE orders AS SELECT * FROM "
        "(VALUES (10, '1', 5.0, 'web'), (11, '1', 7.5, 'shop'), (12, '9', 1.0, 'web')) "
        "t(order_id, customer_id, amount, city)"
    )
    return con


def src(con: duckdb.DuckDBPyConnection, table: str, dataset_id: int) -> SourceTable:
    cols = con.execute(f"DESCRIBE {table}").fetchall()
    return SourceTable(dataset_id, table, f"{table}.csv", tuple((c[0], c[0].title()) for c in cols))


def test_stack(con: duckdb.DuckDBPyConnection) -> None:
    plan = stack_plan([src(con, "s2023", 1), src(con, "s2024", 2)])
    report = run_combine(con, "both_years", plan)
    assert report.row_count == 3
    rows = con.execute("SELECT id, score, source_file FROM both_years ORDER BY id").fetchall()
    assert rows == [(1, None, "s2023.csv"), (2, None, "s2023.csv"), (3, 5, "s2024.csv")]
    codes = {w["code"] for w in report.warnings}
    assert {"stack_partial_columns", "combined_stack"} <= codes
    assert {c.name: c.original_name for c in report.columns}["source_file"] == "source file"


def test_join_renames_clashes_and_reports_matches(con: duckdb.DuckDBPyConnection) -> None:
    plan = join_plan(src(con, "orders", 1), src(con, "customers", 2), "customer_id", "id", "left")
    report = run_combine(con, "orders_customers", plan)
    names = [c.name for c in report.columns]
    assert names == ["order_id", "customer_id", "amount", "city", "name", "customers_city"]
    originals = {c.name: c.original_name for c in report.columns}
    assert originals["customers_city"] == "City (customers.csv)"
    rows = con.execute(
        "SELECT order_id, name, customers_city FROM orders_customers ORDER BY order_id"
    ).fetchall()
    # Text key '1' matches integer key 1; order 12 has no customer.
    assert rows == [(10, "Ann", "Paris"), (11, "Ann", "Paris"), (12, None, None)]
    join_note = next(w for w in report.warnings if w["code"] == "combined_join")
    assert join_note["details"] == {"left_rows": 3, "matched": 2}


def test_join_that_multiplies_rows_is_flagged(con: duckdb.DuckDBPyConnection) -> None:
    plan = join_plan(src(con, "customers", 1), src(con, "orders", 2), "id", "customer_id", "left")
    report = run_combine(con, "customers_orders", plan)
    assert report.row_count == 3  # Ann appears twice, Bo once with no orders
    assert "join_multiplied_rows" in {w["code"] for w in report.warnings}


def test_join_rejects_unknown_key(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError):
        join_plan(src(con, "orders", 1), src(con, "customers", 2), "nope", "id", "left")


def col(name: str, kind: str, semantic: str, **profile: object) -> CompareColumn:
    return CompareColumn(name, name, "X", semantic, {"kind": kind, **profile})


def test_compare_finds_mismatches() -> None:
    a = CompareTable(1, "2023.csv", 100, (
        col("Weight", "numeric", "numeric", numeric={"median": 70.0}, missing_pct=0.0),
        col("sex", "text", "categorical", top_values=[{"value": "Male"}, {"value": "Female"}]),
        col("income", "numeric", "numeric", numeric={"median": 50.0}, missing_pct=0.05),
        col("only_2023", "text", "categorical"),
    ))  # fmt: skip
    b = CompareTable(2, "2024.csv", 120, (
        col("weight", "numeric", "numeric", numeric={"median": 154.0}, missing_pct=0.0),
        col("Sex", "text", "categorical", top_values=[{"value": "M"}, {"value": "F"}]),
        col("income", "text", "categorical", missing_pct=0.6),
    ))  # fmt: skip
    result = compare([a, b])
    by_column = {i["column"]: i["code"] for i in result["issues"]}
    assert by_column == {
        "Weight": "scale_mismatch",
        "sex": "category_mismatch",
        "income": "type_mismatch",
    }
    assert result["shared_columns"] == 3 and result["total_columns"] == 4
    assert result["stackable"] is True
    only = next(c for c in result["columns"] if c["key"] == "only2023")
    assert only["in_all"] is False and list(only["cells"]) == ["1"]


def test_compare_ignores_id_ranges() -> None:
    a = CompareTable(1, "a.csv", 10, (col("id", "numeric", "identifier", numeric={"median": 5}),))
    b = CompareTable(2, "b.csv", 10, (col("id", "numeric", "identifier", numeric={"median": 500}),))
    assert compare([a, b])["issues"] == []
