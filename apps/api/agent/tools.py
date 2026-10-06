"""Tools the chat agent may call, and their implementations.

The model only ever sees metadata, aggregate statistics, masked sample values and query results
capped at ROW_LIMIT rows. Values from personal-data columns are masked in results sent to the
model; the researcher still sees them in the app.
"""

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from api.agent.catalog import Catalog, CatalogColumn, CatalogTable
from api.semantic.describer import column_evidence
from api.semantic.pii import scrub
from api.sql.executor import ROW_LIMIT, QueryResult
from api.stats.tests import COLUMN_LAYOUT, TESTS, StatTestError, run_test

WIDE_COLUMNS = 50  # above this, the schema lists columns briefly and search_columns is advised
MAX_RESULT_CHARS = 24_000  # rows sent to the model are cut to fit this
STAT_ROW_LIMIT = 200_000
MAX_SQL_RETRIES = 3
SEARCH_LIMIT = 10
CHART_TYPES = ("bar", "line", "scatter", "pie")
PII_MASK = "<personal data>"


@dataclass(frozen=True)
class SqlRun:
    query_id: int | None
    result: QueryResult


# Runs a guarded, logged query: (sql, row_limit) -> SqlRun
RunSql = Callable[[str, int], Awaitable[SqlRun]]


@dataclass
class AgentConfig:
    """Switches for the experiments in plan.md section 6 (Phase 5)."""

    include_profile: bool = True  # experiment 1: schema only versus schema plus profile
    include_descriptions: bool = True  # experiment 2
    self_correction: bool = True  # experiment 3
    column_retrieval: bool = True  # experiment 6


@dataclass
class ToolContext:
    catalog: Catalog
    run_sql: RunSql
    config: AgentConfig = field(default_factory=AgentConfig)
    # State for one question
    queries: dict[int, QueryResult] = field(default_factory=dict)
    query_order: list[int] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)  # everything returned to the model
    sql_failures: int = 0
    sql_retries: int = 0
    next_local_id: int = -1  # for queries not logged (no database), ids count down from -1


class ToolError(ValueError):
    """Bad tool arguments. The message goes back to the model."""


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> Any:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS: list[dict[str, Any]] = [
    _fn(
        "get_schema",
        "List the tables and columns with types, descriptions and key statistics. "
        "Pass a table name to see only that table.",
        {"table": {"type": "string", "description": "Optional table name."}},
        [],
    ),
    _fn(
        "get_column_profile",
        "Full profile of one column: missing values, distribution, quantiles, frequent values, "
        "date range and data-quality warnings.",
        {"table": {"type": "string"}, "column": {"type": "string"}},
        ["table", "column"],
    ),
    _fn(
        "search_columns",
        "Find columns whose name or description matches a phrase. Use on wide tables.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _fn(
        "run_sql",
        "Run one read-only DuckDB SELECT over the project tables. Returns at most "
        f"{ROW_LIMIT} rows plus the true row count. Use it for every number you report.",
        {"sql": {"type": "string"}},
        ["sql"],
    ),
    _fn(
        "run_stat_test",
        "Run a statistical test from the fixed library on the two columns a SELECT returns. "
        + " ".join(f"{t}: {COLUMN_LAYOUT[t]}." for t in TESTS),
        {
            "test": {"type": "string", "enum": list(TESTS)},
            "sql": {"type": "string", "description": "SELECT returning exactly two columns."},
        },
        ["test", "sql"],
    ),
    _fn(
        "make_chart",
        "Create a chart from the result of an earlier run_sql call.",
        {
            "query_id": {"type": "integer"},
            "type": {"type": "string", "enum": list(CHART_TYPES)},
            "x": {"type": "string", "description": "Result column for the x axis or labels."},
            "y": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Numeric result columns to plot.",
            },
            "title": {"type": "string"},
        },
        ["query_id", "type", "x", "y", "title"],
    ),
    _fn(
        "final_answer",
        "Finish with the answer. kind is 'answer', 'clarification' (ask the user to choose "
        "between interpretations, listing them in options), or 'cannot_answer' (say what is "
        "missing).",
        {
            "kind": {"type": "string", "enum": ["answer", "clarification", "cannot_answer"]},
            "text": {"type": "string", "description": "The answer in Markdown."},
            "query_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Queries whose results support the answer.",
            },
            "chart_id": {"type": "integer"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        ["kind", "text"],
    ),
]
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}


def tool_specs(config: AgentConfig) -> list[dict[str, Any]]:
    if config.column_retrieval:
        return TOOL_SPECS
    return [t for t in TOOL_SPECS if t["function"]["name"] != "search_columns"]


# ---- schema and profiles ---------------------------------------------------------------


def column_summary(column: CatalogColumn, catalog: Catalog, config: AgentConfig) -> dict[str, Any]:
    if config.include_profile:
        out = column_evidence(
            column.name,
            column.label,
            column.semantic_type,
            column.is_pii,
            column.profile,
            catalog.share_samples,
        )
        if out.get("header") == column.name:
            out.pop("header")
    else:
        out = {"name": column.name, "type": column.semantic_type, "sql_type": column.physical_type}
    if config.include_descriptions and column.description:
        out["description"] = column.description
        if column.confidence == "low" and column.description_source == "llm":
            out["description_is_guess"] = True
    return out


def brief_column(column: CatalogColumn, config: AgentConfig) -> str:
    text = f"{column.name} ({column.semantic_type or column.physical_type})"
    if config.include_descriptions and column.description:
        text += f": {_clip(column.description, 80)}"
    return text


def schema_context(catalog: Catalog, config: AgentConfig, table: str | None = None) -> Any:
    tables = catalog.tables
    if table is not None:
        found = catalog.table(table)
        if found is None:
            raise ToolError(_unknown_table(table, catalog))
        tables = [found]
    wide = sum(len(t.columns) for t in tables) > WIDE_COLUMNS
    out: dict[str, Any] = {
        "tables": [
            {
                "table": t.name,
                "file": t.filename,
                "rows": t.row_count,
                "columns": [
                    brief_column(c, config) if wide else column_summary(c, catalog, config)
                    for c in t.columns
                ],
            }
            for t in tables
        ]
    }
    if catalog.joins and table is None:
        out["possible_joins"] = catalog.joins
    if wide:
        out["note"] = (
            "Many columns, so they are listed briefly. Use search_columns to find columns and "
            "get_column_profile for details."
        )
    return out


def column_profile(catalog: Catalog, config: AgentConfig, table: str, column: str) -> Any:
    t = catalog.table(table)
    if t is None:
        raise ToolError(_unknown_table(table, catalog))
    c = t.column(column)
    if c is None:
        raise ToolError(f"Table {t.name} has no column '{column}'. Use get_schema to list them.")

    out = column_summary(c, catalog, config)
    p = c.profile
    out.update(
        {
            "missing": p.get("missing"),
            "missing_pct": round(p.get("missing_pct", 0) * 100, 2),
            "distinct": p.get("distinct"),
            "uniqueness": _round(p.get("uniqueness")),
        }
    )
    numeric = p.get("numeric")
    if numeric and numeric.get("finite"):
        out["numeric"] = {
            k: _round(numeric.get(k))
            for k in ("min", "max", "mean", "median", "std", "skew", "outliers", "zero_share")
        }
        out["numeric"]["quantiles"] = {k: _round(v) for k, v in numeric["quantiles"].items()}
    dates = p.get("datetime")
    if dates:
        out["datetime"] = {
            k: dates.get(k) for k in ("min", "max", "granularity", "period", "empty_periods")
        }
    categorical = p.get("categorical")
    if categorical:
        out["categorical"] = {k: _round(v) for k, v in categorical.items()}
    if catalog.share_samples and not c.is_pii and p.get("top_values"):
        out["frequent_values"] = [
            {"value": _clip(scrub(str(v["value"])), 60), "count": v["count"]}
            for v in p["top_values"][:15]
        ]
    warnings = [w["message"] for w in t.warnings if w.get("column") == c.name]
    if warnings:
        out["warnings"] = warnings
    return out


def search_columns(catalog: Catalog, query: str) -> Any:
    """Rank columns by word overlap with name, header and description."""
    words = _words(query)
    if not words:
        raise ToolError("Give a phrase to search for.")
    scored = []
    for t in catalog.tables:
        for c in t.columns:
            name_words = _words(f"{c.name} {c.label}")
            text_words = _words(c.description or "")
            score = 2 * _overlap(words, name_words) + _overlap(words, text_words)
            if score > 0:
                scored.append((score, t.name, c))
    scored.sort(key=lambda s: -s[0])
    return {
        "matches": [
            {
                "table": table,
                "column": c.name,
                "type": c.semantic_type,
                "description": c.description,
            }
            for _, table, c in scored[:SEARCH_LIMIT]
        ]
    }


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1}


def _overlap(query: set[str], words: set[str]) -> float:
    # Prefix matches count, so "experience" finds "exp_years" and "exp" finds "experience".
    return sum(
        1.0 if q in words else 0.5
        for q in query
        if q in words
        or any(len(min(q, w, key=len)) >= 3 and (w.startswith(q) or q.startswith(w)) for w in words)
    )


# ---- queries ----------------------------------------------------------------------------


async def run_sql(ctx: ToolContext, sql: str) -> Any:
    if ctx.sql_failures > 0 and ctx.sql_retries >= MAX_SQL_RETRIES:
        raise ToolError(
            f"The query failed {ctx.sql_failures} times in a row and the retry limit is reached. "
            "Do not run more SQL; call final_answer and explain what could not be computed."
        )
    run = await ctx.run_sql(sql, ROW_LIMIT)
    query_id = _register(ctx, run)
    r = run.result
    if r.error:
        if ctx.sql_failures > 0:
            ctx.sql_retries += 1
        ctx.sql_failures += 1
        out: dict[str, Any] = {"query_id": query_id, "error": r.error}
        if not ctx.config.self_correction:
            out["note"] = "Retrying is disabled. Call final_answer."
            ctx.sql_retries = MAX_SQL_RETRIES
        else:
            left = MAX_SQL_RETRIES - ctx.sql_retries
            out["note"] = f"Fix the query and try again ({left} retries left)."
        return out

    ctx.sql_failures = 0
    ctx.sql_retries = 0
    rows = mask_rows(r, ctx.catalog.pii_columns)
    shown, cut = _fit_rows(rows)
    out = {
        "query_id": query_id,
        "columns": r.columns,
        "rows": shown,
        "row_count": r.row_count,
    }
    if r.truncated or cut:
        out["note"] = f"Showing {len(shown)} of {r.row_count} rows."
    return out


async def run_stat_test(ctx: ToolContext, test: str, sql: str) -> Any:
    if test not in TESTS:
        raise ToolError(f"Unknown test '{test}'. Available: {', '.join(TESTS)}.")
    run = await ctx.run_sql(sql, STAT_ROW_LIMIT)
    query_id = _register(ctx, run)
    r = run.result
    if r.error:
        return {"query_id": query_id, "error": r.error, "note": "Fix the query and try again."}
    if len(r.columns) != 2:
        raise ToolError(f"{test} needs a query returning {COLUMN_LAYOUT[test]}.")
    try:
        result = run_test(test, r.rows)
    except StatTestError as exc:
        return {"query_id": query_id, "error": str(exc)}
    result["query_id"] = query_id
    result["columns"] = r.columns
    if r.truncated:
        result["note"] = f"Tested on the first {len(r.rows)} of {r.row_count} rows."
    result["caveat"] = "Exploratory: a significant result is a hypothesis to test, not a finding."
    return result


def make_chart(ctx: ToolContext, query_id: int, type: str, x: str, y: list[str], title: str) -> Any:
    result = ctx.queries.get(query_id)
    if result is None or result.error:
        raise ToolError(f"No successful query with id {query_id} in this answer.")
    if type not in CHART_TYPES:
        raise ToolError(f"Chart type must be one of {', '.join(CHART_TYPES)}.")
    missing = [c for c in [x, *y] if c not in result.columns]
    if missing:
        raise ToolError(
            f"Columns not in the result: {', '.join(missing)}. "
            f"Available: {', '.join(result.columns)}."
        )
    if not y:
        raise ToolError("Give at least one y column.")
    if type == "pie" and len(y) != 1:
        raise ToolError("A pie chart takes exactly one y column.")
    chart_id = len(ctx.charts) + 1
    ctx.charts.append(
        {
            "chart_id": chart_id,
            "query_id": query_id,
            "type": type,
            "x": x,
            "y": y,
            "title": _clip(title, 200),
            "data": [dict(zip(result.columns, row, strict=True)) for row in result.rows],
        }
    )
    return {"chart_id": chart_id, "points": len(result.rows)}


def _register(ctx: ToolContext, run: SqlRun) -> int:
    query_id = run.query_id
    if query_id is None:
        query_id = ctx.next_local_id
        ctx.next_local_id -= 1
    ctx.queries[query_id] = run.result
    ctx.query_order.append(query_id)
    return query_id


def mask_rows(result: QueryResult, pii_columns: set[str]) -> list[list[Any]]:
    """Rows as the model sees them: personal-data columns masked, other text scrubbed."""
    masked = [c.lower() in pii_columns for c in result.columns]
    return [
        [
            PII_MASK if m and v is not None else scrub(v) if isinstance(v, str) else v
            for v, m in zip(row, masked, strict=True)
        ]
        for row in result.rows
    ]


def _fit_rows(rows: list[list[Any]]) -> tuple[list[list[Any]], bool]:
    total = 0
    for i, row in enumerate(rows):
        total += len(json.dumps(row, default=str))
        if total > MAX_RESULT_CHARS:
            return rows[:i], True
    return rows, False


# ---- dispatch ---------------------------------------------------------------------------


async def call_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> Any:
    """Run one tool and return its JSON-able result. Errors become {"error": ...}."""
    try:
        if name == "get_schema":
            out = schema_context(ctx.catalog, ctx.config, _opt_str(args, "table"))
        elif name == "get_column_profile":
            out = column_profile(ctx.catalog, ctx.config, _str(args, "table"), _str(args, "column"))
        elif name == "search_columns" and ctx.config.column_retrieval:
            out = search_columns(ctx.catalog, _str(args, "query"))
        elif name == "run_sql":
            out = await run_sql(ctx, _str(args, "sql"))
        elif name == "run_stat_test":
            out = await run_stat_test(ctx, _str(args, "test"), _str(args, "sql"))
        elif name == "make_chart":
            y = args.get("y")
            if isinstance(y, str):
                y = [y]
            if not isinstance(y, list) or not all(isinstance(v, str) for v in y):
                raise ToolError("y must be a list of column names.")
            out = make_chart(
                ctx, _int(args, "query_id"), _str(args, "type"), _str(args, "x"), y,
                _str(args, "title"),
            )  # fmt: skip
        else:
            raise ToolError(f"Unknown tool '{name}'.")
    except ToolError as exc:
        out = {"error": str(exc)}
    ctx.outputs.append(out)
    return out


def _str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"'{key}' is required and must be text.")
    return value


def _opt_str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _int(args: dict[str, Any], key: str) -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or int(value) != value:
        raise ToolError(f"'{key}' must be an integer.")
    return int(value)


def _unknown_table(name: str, catalog: Catalog) -> str:
    return f"Unknown table '{name}'. Tables: {', '.join(t.name for t in catalog.tables)}."


def _round(value: Any) -> Any:
    return round(value, 4) if isinstance(value, float) else value


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def tables_overview(tables: list[CatalogTable]) -> str:
    return ", ".join(f"{t.name} ({t.row_count} rows, {len(t.columns)} columns)" for t in tables)
