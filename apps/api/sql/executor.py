"""Run a guarded query against a project's DuckDB file.

Second layer of protection after the guard: the file is opened read-only, external access
(files, network, extensions) is disabled and the configuration is locked. Queries are
interrupted after a timeout and results are capped.
"""

import datetime as dt
import math
import threading
import time
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from api.config import get_settings
from api.sql.guard import GuardError, check_sql

ROW_LIMIT = 200
TIMEOUT_S = 30.0


@dataclass
class QueryResult:
    sql: str  # the validated SQL that ran (or was rejected)
    columns: list[str]
    types: list[str]
    rows: list[list[Any]]
    row_count: int  # true number of rows the query returns
    truncated: bool
    duration_ms: int
    error: str | None = None


def run_query(
    db_path: Path,
    sql: str,
    allowed_tables: Collection[str],
    *,
    row_limit: int = ROW_LIMIT,
    timeout_s: float = TIMEOUT_S,
) -> QueryResult:
    started = time.perf_counter()

    def failed(message: str, ran: str = sql) -> QueryResult:
        elapsed = round((time.perf_counter() - started) * 1000)
        return QueryResult(ran, [], [], [], 0, False, elapsed, message)

    try:
        checked = check_sql(sql, allowed_tables)
    except GuardError as exc:
        return failed(str(exc))
    if not db_path.exists():
        return failed("This project has no data yet.", checked)

    con = duckdb.connect(
        str(db_path),
        read_only=True,
        config={
            "enable_external_access": False,
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
            "memory_limit": get_settings().duckdb_memory_limit,
            "threads": 2,
            "lock_configuration": True,
        },
    )
    timer = threading.Timer(timeout_s, con.interrupt)
    timer.start()
    try:
        cursor = con.execute(f"SELECT * FROM ({checked}) AS q LIMIT {row_limit + 1}")
        columns = [d[0] for d in cursor.description or []]
        types = [str(d[1]) for d in cursor.description or []]
        rows = cursor.fetchall()
        truncated = len(rows) > row_limit
        row_count = len(rows)
        if truncated:
            result = con.execute(f"SELECT count(*) FROM ({checked}) AS q").fetchone()
            row_count = int(result[0]) if result else row_count
            rows = rows[:row_limit]
    except duckdb.InterruptException:
        return failed(f"The query took longer than {timeout_s:g} s and was stopped.", checked)
    except duckdb.Error as exc:
        return failed(f"{type(exc).__name__}: {str(exc).splitlines()[0]}", checked)
    finally:
        timer.cancel()
        con.close()

    return QueryResult(
        sql=checked,
        columns=columns,
        types=types,
        rows=[[_json_value(v) for v in row] for row in rows],
        row_count=row_count,
        truncated=truncated,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )


def _json_value(v: Any) -> Any:
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dt.date | dt.datetime | dt.time):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, list | tuple):
        return [_json_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_value(x) for k, x in v.items()}
    return v
