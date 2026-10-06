"""Build a combined table from tables already in the project.

Stack: rows of several tables appended, matching columns by name, with a `source_file` column.
Join: two tables joined on one key column each; clashing column names from the right table are
prefixed with its table name. Keys are compared as text so an integer key can match a text key.
"""

from dataclasses import dataclass, field
from typing import Literal

import duckdb

from api.ingest.loader import LoadedColumn, LoadReport
from api.ingest.names import quote, sanitize_identifier
from api.profiler.warnings import DataWarning, warning


@dataclass(frozen=True)
class SourceTable:
    dataset_id: int
    table_name: str
    label: str  # file name shown to the user
    columns: tuple[tuple[str, str], ...]  # (safe name, original header)


@dataclass
class CombinePlan:
    sql: str
    originals: dict[str, str]  # output column -> header shown to the user
    mode: Literal["stack", "join"]
    sources: list[SourceTable]
    left_key: str | None = None
    right_key: str | None = None
    how: Literal["left", "inner"] = "left"
    notes: list[DataWarning] = field(default_factory=list)


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def stack_plan(sources: list[SourceTable]) -> CombinePlan:
    taken = {name for s in sources for name, _ in s.columns}
    source_col = sanitize_identifier("source_file", taken)
    originals: dict[str, str] = {}
    for s in sources:
        for name, original in s.columns:
            originals.setdefault(name, original)
    originals[source_col] = "source file"
    sql = " UNION ALL BY NAME ".join(
        f"SELECT *, {_literal(s.label)} AS {quote(source_col)} FROM {quote(s.table_name)}"
        for s in sources
    )

    notes: list[DataWarning] = []
    everywhere = set.intersection(*({n for n, _ in s.columns} for s in sources))
    partial = sorted({n for s in sources for n, _ in s.columns} - everywhere)
    if partial:
        listed = ", ".join(f"'{originals[n]}'" for n in partial[:8])
        more = f" and {len(partial) - 8} more" if len(partial) > 8 else ""
        notes.append(
            warning(
                "stack_partial_columns",
                "warning",
                f"{len(partial)} column(s) are not in every file ({listed}{more}); rows from "
                "files without them are missing there.",
                details={"columns": partial},
            )
        )
    return CombinePlan(sql=sql, originals=originals, mode="stack", sources=sources, notes=notes)


def join_plan(
    left: SourceTable,
    right: SourceTable,
    left_key: str,
    right_key: str,
    how: Literal["left", "inner"],
) -> CombinePlan:
    left_names = {n for n, _ in left.columns}
    if left_key not in left_names or right_key not in {n for n, _ in right.columns}:
        raise ValueError("The join key is not a column of the chosen table.")

    taken = set(left_names)
    select = [f"l.{quote(n)} AS {quote(n)}" for n, _ in left.columns]
    originals = dict(left.columns)
    for name, original in right.columns:
        if name == right_key:
            continue  # same values as the left key on every matched row
        out = (
            name if name not in taken else sanitize_identifier(f"{right.table_name}_{name}", taken)
        )
        taken.add(out)
        select.append(f"r.{quote(name)} AS {quote(out)}")
        originals[out] = original if out == name else f"{original} ({right.label})"

    join = "LEFT JOIN" if how == "left" else "INNER JOIN"
    sql = (
        f"SELECT {', '.join(select)} FROM {quote(left.table_name)} AS l {join} "
        f"{quote(right.table_name)} AS r "
        f"ON l.{quote(left_key)}::VARCHAR = r.{quote(right_key)}::VARCHAR"
    )
    return CombinePlan(
        sql=sql,
        originals=originals,
        mode="join",
        sources=[left, right],
        left_key=left_key,
        right_key=right_key,
        how=how,
    )


def run_combine(con: duckdb.DuckDBPyConnection, table_name: str, plan: CombinePlan) -> LoadReport:
    """Create the combined table and report it like a loaded CSV."""
    con.execute(f"CREATE OR REPLACE TABLE {quote(table_name)} AS {plan.sql}")
    columns = [
        LoadedColumn(
            name=row[0], original_name=plan.originals.get(row[0], row[0]), physical_type=row[1]
        )
        for row in con.execute(f"DESCRIBE {quote(table_name)}").fetchall()
    ]
    result = con.execute(f"SELECT count(*) FROM {quote(table_name)}").fetchone()
    rows = int(result[0]) if result else 0

    notes = list(plan.notes)
    if plan.mode == "stack":
        notes.append(
            warning(
                "combined_stack",
                "info",
                f"Stacked {len(plan.sources)} files: "
                + ", ".join(s.label for s in plan.sources)
                + ". The 'source file' column says which file each row came from.",
            )
        )
    else:
        notes += _join_notes(con, plan, rows)
    return LoadReport(table_name=table_name, row_count=rows, columns=columns, warnings=notes)


def _join_notes(con: duckdb.DuckDBPyConnection, plan: CombinePlan, rows: int) -> list[DataWarning]:
    left, right = plan.sources
    lk, rk = quote(plan.left_key or ""), quote(plan.right_key or "")
    counts = con.execute(
        f"""
        SELECT (SELECT count(*) FROM {quote(left.table_name)}),
               (SELECT count(*) FROM {quote(left.table_name)} AS l
                WHERE EXISTS (SELECT 1 FROM {quote(right.table_name)} AS r
                              WHERE l.{lk}::VARCHAR = r.{rk}::VARCHAR))
        """
    ).fetchone()
    left_rows, matched = (int(x) for x in counts) if counts else (0, 0)
    share = matched / left_rows if left_rows else 0.0

    notes = [
        warning(
            "combined_join",
            "info",
            f"Joined {left.label} to {right.label} ({plan.how} join). {matched} of {left_rows} "
            f"rows of {left.label} ({share:.0%}) found a match.",
            details={"left_rows": left_rows, "matched": matched},
        )
    ]
    if share < 0.5:
        notes.append(
            warning(
                "join_low_match",
                "warning",
                f"Only {share:.0%} of rows in {left.label} found a match; check that the key "
                "columns hold the same kind of identifier.",
                details={"share": share},
            )
        )
    if rows > left_rows and plan.how == "left":
        notes.append(
            warning(
                "join_multiplied_rows",
                "warning",
                f"The join produced {rows} rows from {left_rows}: some keys appear more than "
                f"once in {right.label}, so rows of {left.label} were repeated. Counts and "
                "averages over the combined table can be inflated.",
                details={"rows": rows, "left_rows": left_rows},
            )
        )
    return notes
