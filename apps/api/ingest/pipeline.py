"""Synchronous load and profile steps, run by the worker in a thread.

Each step opens the project's DuckDB file itself; the worker holds a per-project lock so only
one writer touches a file at a time.
"""

from pathlib import Path
from typing import Any

import duckdb

from api.config import get_settings
from api.ingest.combine import CombinePlan, run_combine
from api.ingest.formats import load_file
from api.ingest.loader import LoadReport
from api.ingest.names import quote
from api.profiler.joins import JoinTable, find_joins
from api.profiler.tables import DatasetProfile, profile_table
from api.semantic.pii import PiiResult, detect


def connect(db_path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(
        str(db_path),
        read_only=read_only,
        config={
            "memory_limit": get_settings().duckdb_memory_limit,
            "enable_external_access": True,  # needed to read the uploaded CSV
        },
    )


def run_load(db_path: Path, path: Path, table_name: str, kind: str = "csv") -> LoadReport:
    with connect(db_path) as con:
        return load_file(con, path, table_name, kind)


def run_combine_plan(db_path: Path, table_name: str, plan: CombinePlan) -> LoadReport:
    with connect(db_path) as con:
        return run_combine(con, table_name, plan)


def run_profile(db_path: Path, report: LoadReport) -> DatasetProfile:
    with connect(db_path) as con:
        return profile_table(con, report)


def run_pii(db_path: Path, profile: DatasetProfile, table_name: str) -> dict[str, PiiResult]:
    with connect(db_path) as con:
        return {
            r.column.name: detect(con, table_name, r.column.name, r.column.physical_type, r.profile)
            for r in profile.columns
        }


def drop_table(db_path: Path, table_name: str) -> None:
    if not db_path.exists():
        return
    with connect(db_path) as con:
        con.execute(f"DROP TABLE IF EXISTS {quote(table_name)}")


def run_joins(db_path: Path, new: JoinTable, others: list[JoinTable]) -> list[dict[str, Any]]:
    if not others:
        return []
    with connect(db_path) as con:
        return find_joins(con, new, others)
