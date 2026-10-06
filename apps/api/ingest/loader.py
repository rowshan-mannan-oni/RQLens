"""Load a CSV file into a DuckDB table.

Steps: read with auto-detection (delimiter, quoting, header, types) treating common placeholder
strings as missing; record rows that failed to parse; fall back to Latin-1 for non-UTF-8 files;
re-type text columns that are really numbers or dates; rename columns to safe identifiers.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from api.ingest.names import quote, sanitize_identifier
from api.profiler.warnings import DataWarning, warning

# Cell values read as missing. "-999"-style numeric codes are flagged by the profiler instead,
# because they cannot be told apart from real values without the researcher.
NULL_STRINGS = [
    "", "NA", "N/A", "n/a", "na", "NaN", "nan", "NULL", "null", "Null", "None", "none",
    "?", "-", "--", ".", "#N/A", "missing", "MISSING",
]  # fmt: skip

# A text column is re-typed when at least this share of its non-missing values parse.
TYPE_FIX_THRESHOLD = 0.98
EXAMPLE_LIMIT = 5


@dataclass(frozen=True)
class LoadedColumn:
    name: str  # safe identifier used in SQL
    original_name: str  # header as written in the file
    physical_type: str


@dataclass
class LoadReport:
    table_name: str
    row_count: int
    columns: list[LoadedColumn]
    warnings: list[DataWarning] = field(default_factory=list)
    # Column descriptions found in the file itself (SPSS and Stata variable labels), by the
    # safe column name. Stored like a data dictionary.
    descriptions: dict[str, str] = field(default_factory=dict)


def load_csv(con: duckdb.DuckDBPyConnection, csv_path: Path, table_name: str) -> LoadReport:
    """Create (or replace) `table_name` from the CSV. `table_name` must be a safe identifier."""
    raw = f"__raw_{table_name}"
    rejects, scans = f"__rejects_{table_name}", f"__scans_{table_name}"
    warnings: list[DataWarning] = []

    # With ignore_errors, invalid UTF-8 usually rejects rows instead of raising, so check both.
    try:
        _read_csv(con, csv_path, raw, rejects, scans, encoding="utf-8")
        bad_unicode = con.execute(
            f"SELECT count(*) FROM {quote(rejects)} "
            "WHERE error_type IN ('INVALID ENCODING', 'INVALID UNICODE')"
        ).fetchone()
        not_utf8 = bool(bad_unicode and bad_unicode[0])
    except duckdb.InvalidInputException as exc:
        if "unicode" not in str(exc).lower():
            raise
        not_utf8 = True

    if not_utf8:
        con.execute(f"DROP TABLE IF EXISTS {quote(rejects)}; DROP TABLE IF EXISTS {quote(scans)}")
        _read_csv(con, csv_path, raw, rejects, scans, encoding="latin-1")
        warnings.append(
            warning(
                "encoding_fallback",
                "info",
                "The file is not valid UTF-8, so it was read as Latin-1. "
                "Check that accented characters look right.",
            )
        )

    warnings += _rejected_rows(con, rejects)
    con.execute(f"DROP TABLE IF EXISTS {quote(rejects)}; DROP TABLE IF EXISTS {quote(scans)}")
    return finish_load(con, raw, table_name, warnings)


def finish_load(
    con: duckdb.DuckDBPyConnection, raw: str, table_name: str, warnings: list[DataWarning]
) -> LoadReport:
    """Turn the raw table into `table_name`: safe column names, and text columns that are
    really numbers or dates re-typed. Drops the raw table."""
    raw_columns: list[tuple[str, str]] = [
        (row[0], row[1]) for row in con.execute(f"DESCRIBE {quote(raw)}").fetchall()
    ]
    if raw_columns and all(re.fullmatch(r"column\d+", c) for c, _ in raw_columns):
        warnings.append(
            warning(
                "no_header",
                "warning",
                "No header row was detected, so columns were named column0, column1, ...",
            )
        )

    taken: set[str] = set()
    select_list: list[str] = []
    columns: list[LoadedColumn] = []
    for original, physical in raw_columns:
        name = sanitize_identifier(original, taken)
        expr = quote(original)
        if physical == "VARCHAR":
            fix = _better_type(con, raw, original)
            if fix is not None:
                physical, coerced, examples = fix
                expr = f"TRY_CAST(NULLIF(trim({expr}), '') AS {physical})"
                if coerced:
                    warnings.append(
                        warning(
                            "coerced_values",
                            "warning",
                            f"'{original}' is mostly {_type_label(physical)}; {coerced} value(s) "
                            "that did not fit were set to missing.",
                            column=name,
                            details={"count": coerced, "examples": examples},
                        )
                    )
        select_list.append(f"{expr} AS {quote(name)}")
        columns.append(LoadedColumn(name=name, original_name=original, physical_type=physical))

    con.execute(
        f"CREATE OR REPLACE TABLE {quote(table_name)} AS "
        f"SELECT {', '.join(select_list)} FROM {quote(raw)}"
    )
    con.execute(f"DROP TABLE {quote(raw)}")

    result = con.execute(f"SELECT count(*) FROM {quote(table_name)}").fetchone()
    row_count = int(result[0]) if result else 0
    return LoadReport(
        table_name=table_name, row_count=row_count, columns=columns, warnings=warnings
    )


def _read_csv(
    con: duckdb.DuckDBPyConnection,
    csv_path: Path,
    raw: str,
    rejects: str,
    scans: str,
    *,
    encoding: str,
) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TABLE {quote(raw)} AS
        SELECT * FROM read_csv(
            $path,
            auto_detect = true,
            sample_size = -1,
            nullstr = $nulls,
            encoding = $encoding,
            ignore_errors = true,
            store_rejects = true,
            rejects_table = $rejects,
            rejects_scan = $scans
        )
        """,
        {
            "path": str(csv_path),
            "nulls": NULL_STRINGS,
            "encoding": encoding,
            "rejects": rejects,
            "scans": scans,
        },
    )


def _rejected_rows(con: duckdb.DuckDBPyConnection, rejects: str) -> list[DataWarning]:
    rows = con.execute(
        f"SELECT line, error_type, error_message FROM {quote(rejects)} ORDER BY line"
    ).fetchall()
    if not rows:
        return []
    lines = sorted({int(r[0]) for r in rows})
    examples = [
        {"line": int(line), "error": str(kind), "message": str(msg)}
        for line, kind, msg in rows[:EXAMPLE_LIMIT]
    ]
    return [
        warning(
            "rejected_rows",
            "warning",
            f"{len(lines)} row(s) could not be parsed and were skipped.",
            details={"count": len(lines), "examples": examples},
        )
    ]


def _better_type(
    con: duckdb.DuckDBPyConnection, raw: str, column: str
) -> tuple[str, int, list[str]] | None:
    """Return (type, values that will become missing, examples) if the text column should be
    re-typed, else None."""
    col = f"NULLIF(trim({quote(column)}), '')"
    row = con.execute(
        f"""
        SELECT count(v),
               count(TRY_CAST(v AS BIGINT)),
               count(TRY_CAST(v AS DOUBLE)),
               count(TRY_CAST(v AS DATE)),
               count(TRY_CAST(v AS TIMESTAMP)),
               count_if(regexp_matches(v, '^[+-]?0[0-9]'))
        FROM (SELECT {col} AS v FROM {quote(raw)})
        """
    ).fetchone()
    if row is None or row[0] == 0:
        return None
    non_null, as_int, as_double, as_date, as_ts, leading_zero = (int(x) for x in row)
    # Codes such as zip codes or "007" lose meaning as numbers.
    if leading_zero:
        return None

    for type_name, ok in (
        ("BIGINT", as_int),
        ("DOUBLE", as_double),
        ("DATE", as_date),
        ("TIMESTAMP", as_ts),
    ):
        if ok / non_null >= TYPE_FIX_THRESHOLD:
            coerced = non_null - ok
            examples: list[str] = []
            if coerced:
                examples = [
                    str(r[0])
                    for r in con.execute(
                        f"SELECT DISTINCT v FROM (SELECT {col} AS v FROM {quote(raw)}) "
                        f"WHERE v IS NOT NULL AND TRY_CAST(v AS {type_name}) IS NULL "
                        f"LIMIT {EXAMPLE_LIMIT}"
                    ).fetchall()
                ]
            return type_name, coerced, examples
    return None


def _type_label(physical: str) -> str:
    return {
        "BIGINT": "whole numbers",
        "DOUBLE": "numbers",
        "DATE": "dates",
        "TIMESTAMP": "date-times",
    }.get(physical, physical)
