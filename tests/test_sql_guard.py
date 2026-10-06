"""SQL guard and executor, including malicious inputs."""

from pathlib import Path

import duckdb
import pytest

from api.sql.executor import run_query
from api.sql.guard import GuardError, check_sql

TABLES = {"survey", "orders"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT gender, count(*) AS n FROM survey GROUP BY gender ORDER BY n DESC",
        "WITH x AS (SELECT * FROM survey) SELECT avg(age) FROM x",
        "SELECT * FROM survey s JOIN orders o ON s.id = o.customer_id",
        "SELECT age, rank() OVER (ORDER BY age) FROM survey",
        "SELECT * FROM survey WHERE age > (SELECT avg(age) FROM survey);",
        "SELECT 1 AS a UNION ALL SELECT 2",
        "SELECT * FROM range(10)",
        "SELECT * FROM main.survey",
        "SELECT quantile_cont(age, 0.5) FROM survey",
    ],
)
def test_allowed(sql: str) -> None:
    check_sql(sql, TABLES)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "DROP TABLE survey",
        "SELECT 1; DROP TABLE survey",
        "DELETE FROM survey",
        "UPDATE survey SET age = 0",
        "INSERT INTO survey VALUES (1)",
        "CREATE TABLE z AS SELECT * FROM survey",
        "COPY survey TO '/tmp/out.csv'",
        "ATTACH '/tmp/other.db' AS other",
        "PRAGMA database_list",
        "SET threads = 1",
        "INSTALL httpfs",
        "LOAD httpfs",
        "EXPORT DATABASE '/tmp/x'",
        "CALL pragma_version()",
        "DESCRIBE survey",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM '/etc/passwd'",
        "SELECT * FROM 'https://example.com/data.csv'",
        "SELECT read_text('/etc/passwd')",
        "SELECT getenv('API_JWT_SECRET')",
        "SELECT current_setting('memory_limit')",
        "SELECT * FROM duckdb_settings()",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM glob('/data/*')",
        "SELECT * FROM query('SELECT 1')",
        "SELECT * FROM other_db.main.survey",
        "SELECT * FROM secrets",
        "WITH x AS (SELECT * FROM read_parquet('/x.parquet')) SELECT * FROM x",
        "SELECT * FROM survey WHERE id IN (SELECT id FROM read_json('/x.json'))",
    ],
)
def test_rejected(sql: str) -> None:
    with pytest.raises(GuardError):
        check_sql(sql, TABLES)


def test_unknown_table_message_lists_tables() -> None:
    with pytest.raises(GuardError, match="Available tables: orders, survey"):
        check_sql("SELECT * FROM surveys", TABLES)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "data.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE survey AS SELECT i AS id, 20 + i % 50 AS age, "
        "CASE WHEN i % 3 = 0 THEN 'M' ELSE 'F' END AS gender, "
        "DATE '2024-01-01' + i::INTEGER AS day FROM range(1000) t(i)"
    )
    con.close()
    return path


def test_execute_with_row_cap_and_true_count(db: Path) -> None:
    result = run_query(db, "SELECT * FROM survey ORDER BY id", {"survey"}, row_limit=50)
    assert result.error is None
    assert result.columns == ["id", "age", "gender", "day"]
    assert len(result.rows) == 50
    assert result.truncated is True
    assert result.row_count == 1000
    assert result.rows[0] == [0, 20, "M", "2024-01-01"]


def test_execute_aggregate(db: Path) -> None:
    result = run_query(
        db, "SELECT gender, count(*) AS n FROM survey GROUP BY gender ORDER BY gender", {"survey"}
    )
    assert result.rows == [["F", 666], ["M", 334]]
    assert result.truncated is False and result.row_count == 2


def test_guard_errors_are_returned_not_raised(db: Path) -> None:
    result = run_query(db, "DROP TABLE survey", {"survey"})
    assert result.error == "Only SELECT queries are allowed."
    assert run_query(db, "SELECT count(*) FROM survey", {"survey"}).rows == [[1000]]


def test_sql_errors_are_returned(db: Path) -> None:
    result = run_query(db, "SELECT no_such_column FROM survey", {"survey"})
    assert result.error is not None and "no_such_column" in result.error


def test_connection_is_read_only_even_without_the_guard(db: Path) -> None:
    con = duckdb.connect(str(db), read_only=True, config={"enable_external_access": False})
    with pytest.raises(duckdb.Error):
        con.execute("CREATE TABLE z AS SELECT 1")
    with pytest.raises(duckdb.Error):
        con.execute("SELECT * FROM read_text('/etc/hostname')")
    con.close()


def test_timeout(db: Path) -> None:
    result = run_query(
        db,
        "SELECT count(*) FROM range(100000000) a, range(1000) b WHERE a.range % 7 = b.range",
        {"survey"},
        timeout_s=0.5,
    )
    assert result.error is not None and "longer than" in result.error
