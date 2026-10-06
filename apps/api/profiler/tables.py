"""Table-level profile and the entry point that profiles a whole loaded table."""

from dataclasses import dataclass
from typing import Any

import duckdb

from api.ingest.loader import LoadedColumn, LoadReport
from api.ingest.names import quote
from api.profiler.columns import profile_column
from api.profiler.relationships import analyse
from api.profiler.warnings import DataWarning, column_warnings, table_warnings


@dataclass
class ColumnResult:
    column: LoadedColumn
    profile: dict[str, Any]


@dataclass
class DatasetProfile:
    columns: list[ColumnResult]
    table: dict[str, Any]
    warnings: list[DataWarning]


def profile_table(con: duckdb.DuckDBPyConnection, report: LoadReport) -> DatasetProfile:
    t = quote(report.table_name)
    rows = report.row_count

    columns = [
        ColumnResult(column=col, profile=profile_column(con, report.table_name, col, rows))
        for col in report.columns
    ]

    distinct_row = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT * FROM {t})").fetchone()
    distinct_rows = int(distinct_row[0]) if distinct_row else 0
    table = {
        "row_count": rows,
        "column_count": len(columns),
        "duplicate_rows": rows - distinct_rows,
        "candidate_keys": [
            r.column.name
            for r in columns
            if rows
            and r.profile["missing"] == 0
            and r.profile["distinct"] == rows
            # Unique dates or measurements are keys only by accident.
            and r.profile["semantic_type"] == "identifier"
        ],
        "semantic_types": _count_by(r.profile["semantic_type"] for r in columns),
        "missing_cells": sum(r.profile["missing"] for r in columns),
        "missing_cells_pct": (
            sum(r.profile["missing"] for r in columns) / (rows * len(columns))
            if rows and columns
            else 0.0
        ),
    }

    table["relationships"] = analyse(
        con, report.table_name, rows, [(r.column, r.profile) for r in columns]
    )

    names = {r.column.name: r.column.original_name for r in columns}
    warnings = list(report.warnings) + table_warnings(table, names)
    for r in columns:
        warnings += column_warnings(r.column.name, r.column.original_name, r.profile)
    return DatasetProfile(columns=columns, table=table, warnings=warnings)


def _count_by(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
