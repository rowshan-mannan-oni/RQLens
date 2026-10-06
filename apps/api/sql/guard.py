"""Validate SQL written by the model before it runs.

Only a single read-only query over the project's own tables is allowed. This is the first of two
layers: the executor also opens DuckDB read-only with external file access disabled.
"""

from collections.abc import Collection

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


class GuardError(ValueError):
    """The query is not allowed. The message is safe to show to the model and the user."""


# Statement types that must not appear anywhere, including inside CTEs.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Copy", "Attach",
        "Detach", "Pragma", "Set", "Command", "Use", "Install", "Describe", "Show", "Load",
        "Into", "Transaction", "Commit", "Rollback",
    )
    if hasattr(exp, name)
)  # fmt: skip

# Table functions that are pure and read no files.
ALLOWED_TABLE_FUNCTIONS: tuple[type[exp.Expression], ...] = (exp.GenerateSeries, exp.Unnest)

# Scalar or table functions that read files, the environment, or database internals.
FORBIDDEN_FUNCTION_PREFIXES = (
    "read_", "glob", "getenv", "query", "duckdb_", "pragma_", "current_setting", "sniff_csv",
    "parquet_", "csv_", "json_scan", "iceberg_", "delta_", "sqlite_", "postgres_", "mysql_",
    "http", "load_", "install_", "checkpoint", "system", "which_secret", "list_files",
)  # fmt: skip


def check_sql(sql: str, allowed_tables: Collection[str]) -> str:
    """Return the validated query as DuckDB SQL, or raise GuardError.

    The returned text is regenerated from the parsed tree, so what runs is exactly what was
    checked.
    """
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise GuardError("The query is empty.")
    try:
        statements = sqlglot.parse(text, read="duckdb")
    except SqlglotError as exc:
        raise GuardError(f"The query could not be parsed: {str(exc).splitlines()[0]}") from exc

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise GuardError("Only one statement is allowed.")
    query = statements[0]
    if not isinstance(query, exp.Query):
        raise GuardError("Only SELECT queries are allowed.")

    for node in query.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardError(f"{type(node).__name__.upper()} is not allowed; only SELECT.")

    ctes = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
    allowed = {t.lower() for t in allowed_tables} | ctes
    for table in query.find_all(exp.Table):
        _check_table(table, allowed)

    for func in query.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name.startswith(FORBIDDEN_FUNCTION_PREFIXES) or type(func).__name__.startswith("Read"):
            raise GuardError(f"The function {name}() is not allowed.")

    return query.sql(dialect="duckdb")


def _check_table(table: exp.Table, allowed: set[str]) -> None:
    source = table.this
    if isinstance(source, exp.Func):
        if not isinstance(source, ALLOWED_TABLE_FUNCTIONS):
            name = source.name if isinstance(source, exp.Anonymous) else source.sql_name()
            raise GuardError(f"The table function {name.lower()}() is not allowed.")
        return
    if table.catalog or (table.db and table.db.lower() != "main"):
        raise GuardError("Only tables in this project can be queried.")
    if table.name.lower() not in allowed:
        raise GuardError(
            f"Unknown table '{table.name}'. Available tables: {', '.join(sorted(allowed))}."
        )
