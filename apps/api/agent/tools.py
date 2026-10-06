"""Tools the chat agent can call, and the per-question state they share.

What the model sees is limited: sample and frequent values only when the project shares
samples, never for personal-data columns, and query results capped at MODEL_ROWS rows with
emails, phone numbers and long digit runs masked. When a query reads a personal-data column,
all text cells in its result are hidden from the model. The user still sees full results in the
"How this was computed" panel.
"""

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from api.agent.grounding import collect_numbers
from api.ingest.names import quote
from api.semantic.pii import scrub
from api.sql.executor import QueryResult
from api.stats.library import TESTS, StatTestError, run_test

MODEL_ROWS = 50
STAT_ROWS = 100_000
WIDE_TABLE = 50
MAX_CHART_SERIES = 4
SAMPLE_KEYS = ("top_values", "samples")
BULKY_KEYS = ("histogram",)  # aggregates, but long and rarely needed to answer a question

# (sql, row limit) -> (query id, result)
Execute = Callable[[str, int], Awaitable[tuple[int, QueryResult]]]


@dataclass
class ColumnInfo:
    name: str
    label: str | None
    physical_type: str
    semantic_type: str | None
    description: str | None
    description_source: str | None
    confidence: str | None
    is_pii: bool
    profile: dict[str, Any] | None


@dataclass
class TableInfo:
    table: str
    filename: str
    rows: int | None
    columns: list[ColumnInfo]


@dataclass
class ProjectContext:
    project_id: int
    topic: str | None
    share_samples: bool
    tables: list[TableInfo]
    joins: list[dict[str, Any]] = field(default_factory=list)

    def table(self, name: str) -> TableInfo:
        for t in self.tables:
            if t.table.lower() == name.lower():
                return t
        raise ToolError(
            f"Unknown table {name!r}. Tables: {', '.join(t.table for t in self.tables)}."
        )

    @property
    def pii_columns(self) -> set[str]:
        return {c.name.lower() for t in self.tables for c in t.columns if c.is_pii}


class ToolError(ValueError):
    """Returned to the model as {"error": ...}."""


@dataclass
class Step:
    tool: str
    args: dict[str, Any]
    summary: str
    error: str | None = None
    query_id: int | None = None
    result: dict[str, Any] | None = None  # stat test result, shown to the user

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ToolState:
    """Everything produced while answering one question."""

    query_ids: list[int] = field(default_factory=list)
    results: dict[int, QueryResult] = field(default_factory=dict)
    charts: list[dict[str, Any]] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    numbers: list[float] = field(default_factory=list)  # every number shown to the model
    sql_errors: int = 0


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> Any:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TEST_HELP = "; ".join(f"{name}: {help_}" for name, (_, help_) in TESTS.items())

TOOL_SPECS: list[dict[str, Any]] = [
    _fn(
        "get_schema",
        "Tables, columns, types and descriptions. Optionally one table only.",
        {"table": {"type": "string"}},
        [],
    ),
    _fn(
        "get_column_profile",
        "Full profile of one column: missing values, distinct count, statistics, frequent "
        "values, date range.",
        {"table": {"type": "string"}, "column": {"type": "string"}},
        ["table", "column"],
    ),
    _fn(
        "search_columns",
        "Find columns whose name or description matches the words in `query`.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _fn(
        "run_sql",
        f"Run one read-only DuckDB SELECT over the project's tables. Returns up to {MODEL_ROWS} "
        "rows and the true row count. Quote identifiers with double quotes.",
        {
            "sql": {"type": "string"},
            "purpose": {"type": "string", "description": "What this query computes, briefly."},
        },
        ["sql", "purpose"],
    ),
    _fn(
        "run_stat_test",
        f"Run a test from the fixed library on two columns of one table. Tests: {TEST_HELP}. "
        "`where` is an optional SQL condition to filter rows first.",
        {
            "test": {"type": "string", "enum": list(TESTS)},
            "table": {"type": "string"},
            "x": {"type": "string"},
            "y": {"type": "string"},
            "where": {"type": "string"},
        },
        ["test", "table", "x", "y"],
    ),
    _fn(
        "make_chart",
        "Chart the result of an earlier run_sql call. `x` is one result column, `y` one or "
        f"more numeric result columns (at most {MAX_CHART_SERIES}).",
        {
            "query_id": {"type": "integer"},
            "type": {"type": "string", "enum": ["bar", "line", "scatter"]},
            "x": {"type": "string"},
            "y": {"type": "array", "items": {"type": "string"}},
            "title": {"type": "string"},
        },
        ["query_id", "type", "x", "y", "title"],
    ),
    _fn(
        "final_answer",
        "Finish. `kind` is answer, clarification (you need the user to choose before you can "
        "answer) or cannot_answer (the data cannot answer it). List the query_ids and "
        "chart_ids the answer relies on.",
        {
            "answer": {"type": "string", "description": "Markdown shown to the user."},
            "kind": {"type": "string", "enum": ["answer", "clarification", "cannot_answer"]},
            "query_ids": {"type": "array", "items": {"type": "integer"}},
            "chart_ids": {"type": "array", "items": {"type": "integer"}},
        },
        ["answer", "kind"],
    ),
]

FINAL_ONLY = [t for t in TOOL_SPECS if t["function"]["name"] == "final_answer"]


class ToolBox:
    def __init__(self, ctx: ProjectContext, execute: Execute) -> None:
        self.ctx = ctx
        self.execute = execute
        self.state = ToolState()

    # ----- schema -----

    def schema(self, table: str | None = None) -> dict[str, Any]:
        tables = [self.ctx.table(table)] if table else self.ctx.tables
        out: list[dict[str, Any]] = []
        for t in tables:
            wide = len(t.columns) > WIDE_TABLE and table is None
            entry: dict[str, Any] = {"table": t.table, "file": t.filename, "rows": t.rows}
            if wide:
                entry["columns"] = [f"{c.name} ({c.semantic_type})" for c in t.columns]
                entry["note"] = (
                    f"{len(t.columns)} columns; descriptions omitted. Use search_columns or "
                    "get_schema with this table."
                )
            else:
                entry["columns"] = [self._column_line(c) for c in t.columns]
            out.append(entry)
        result: dict[str, Any] = {"tables": out}
        if self.ctx.joins and table is None:
            result["possible_joins"] = self.ctx.joins
        return result

    @staticmethod
    def _column_line(c: ColumnInfo) -> dict[str, Any]:
        line: dict[str, Any] = {
            "name": c.name,
            "type": c.semantic_type or c.physical_type,
            "sql_type": c.physical_type,
        }
        if c.label and c.label != c.name:
            line["header"] = c.label
        if c.description:
            line["description"] = c.description
            if c.description_source == "llm" and c.confidence == "low":
                line["description_is_a_guess"] = True
        if c.is_pii:
            line["personal_data"] = True
        p = c.profile or {}
        if p.get("missing_pct"):
            line["missing_pct"] = round(p["missing_pct"] * 100, 1)
        return line

    def column_profile(self, table: str, column: str) -> dict[str, Any]:
        t = self.ctx.table(table)
        col = next((c for c in t.columns if c.name.lower() == column.lower()), None)
        if col is None:
            raise ToolError(f"Table {t.table} has no column {column!r}.")
        hidden = (
            BULKY_KEYS if self.ctx.share_samples and not col.is_pii else BULKY_KEYS + SAMPLE_KEYS
        )
        profile = _drop_keys(col.profile or {}, hidden)
        if col.is_pii:
            for key in ("numeric", "datetime", "text"):
                profile.pop(key, None)
        out = {"table": t.table, **self._column_line(col), "profile": profile}
        clean: dict[str, Any] = json.loads(json.dumps(out, default=str))
        return clean

    def search(self, query: str) -> dict[str, Any]:
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1}
        if not words:
            raise ToolError("The query has no searchable words.")
        scored: list[tuple[int, dict[str, Any]]] = []
        for t in self.ctx.tables:
            for c in t.columns:
                name_words = set(re.findall(r"[a-z0-9]+", f"{c.name} {c.label or ''}".lower()))
                desc_words = set(re.findall(r"[a-z0-9]+", (c.description or "").lower()))
                score = 3 * len(words & name_words) + len(words & desc_words)
                score += sum(1 for w in words if any(n.startswith(w) for n in name_words))
                if score:
                    scored.append((score, {"table": t.table, **self._column_line(c)}))
        scored.sort(key=lambda s: -s[0])
        return {"matches": [m for _, m in scored[:15]]}

    # ----- queries -----

    async def run_sql(self, sql: str) -> tuple[int, dict[str, Any]]:
        query_id, r = await self.execute(sql, 200)
        self._remember(query_id, r)
        if r.error:
            self.state.sql_errors += 1
            raise ToolError(r.error)
        rows = self._model_rows(r)
        out: dict[str, Any] = {
            "query_id": query_id,
            "columns": r.columns,
            "rows": rows,
            "row_count": r.row_count,
        }
        if r.row_count > len(rows):
            out["note"] = f"Showing {len(rows)} of {r.row_count} rows; aggregate in SQL instead."
        return query_id, out

    def _remember(self, query_id: int, r: QueryResult) -> None:
        self.state.query_ids.append(query_id)
        self.state.results[query_id] = r

    def _model_rows(self, r: QueryResult) -> list[list[Any]]:
        hide = self._reads_pii(r.sql)
        rows: list[list[Any]] = []
        for row in r.rows[:MODEL_ROWS]:
            rows.append(
                [("<masked>" if hide else scrub(v)) if isinstance(v, str) else v for v in row]
            )
        return rows

    def _reads_pii(self, sql: str) -> bool:
        pii = self.ctx.pii_columns
        if not pii:
            return False
        try:
            tree = sqlglot.parse_one(sql, read="duckdb")
        except SqlglotError:
            return True
        if any(c.name.lower() in pii for c in tree.find_all(exp.Column)):
            return True
        # SELECT * or t.* (count(*) is fine).
        return any(
            isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
            for select in tree.find_all(exp.Select)
            for e in select.expressions
        )

    async def stat_test(
        self, test: str, table: str, x: str, y: str, where: str | None
    ) -> tuple[int, dict[str, Any]]:
        if test not in TESTS:
            raise ToolError(f"Unknown test {test!r}. Available: {', '.join(TESTS)}.")
        t = self.ctx.table(table)
        names = {c.name.lower(): c.name for c in t.columns}
        for col in (x, y):
            if col.lower() not in names:
                raise ToolError(f"Table {t.table} has no column {col!r}.")
        cx, cy = quote(names[x.lower()]), quote(names[y.lower()])
        inner = f"SELECT {cx} AS x, {cy} AS y FROM {quote(t.table)}"
        if where and where.strip():
            inner += f" WHERE {where}"
        sql = (
            f"SELECT * FROM ({inner}) AS s USING SAMPLE reservoir({STAT_ROWS} ROWS) REPEATABLE (42)"
        )
        query_id, r = await self.execute(sql, STAT_ROWS)
        self._remember(query_id, r)
        if r.error:
            self.state.sql_errors += 1
            raise ToolError(r.error)
        try:
            result = run_test(test, [row[0] for row in r.rows], [row[1] for row in r.rows])
        except StatTestError as exc:
            raise ToolError(str(exc)) from exc
        out = {"query_id": query_id, **result.to_json()}
        if r.row_count > STAT_ROWS:
            out["note"] = (out.get("note") or "") + (
                f" Run on a random sample of {STAT_ROWS} of {r.row_count} rows."
            )
        return query_id, out

    def chart(self, query_id: int, kind: str, x: str, y: list[str], title: str) -> dict[str, Any]:
        r = self.state.results.get(query_id)
        if r is None or r.error:
            raise ToolError(f"No successful query with id {query_id} in this answer.")
        if kind not in ("bar", "line", "scatter"):
            raise ToolError("type must be bar, line or scatter.")
        if not y or len(y) > MAX_CHART_SERIES:
            raise ToolError(f"Give 1 to {MAX_CHART_SERIES} y columns.")
        missing = [c for c in [x, *y] if c not in r.columns]
        if missing:
            raise ToolError(f"Not in the result: {', '.join(missing)}. Columns: {r.columns}.")
        ix = r.columns.index(x)
        iy = [r.columns.index(c) for c in y]
        for c, i in zip(y, iy, strict=True):
            if any(row[i] is not None and not isinstance(row[i], int | float) for row in r.rows):
                raise ToolError(f"Column {c} is not numeric.")
        chart_id = len(self.state.charts) + 1
        self.state.charts.append(
            {
                "id": chart_id,
                "query_id": query_id,
                "type": kind,
                "title": title,
                "x": x,
                "y": y,
                "data": [
                    {x: row[ix], **{c: row[i] for c, i in zip(y, iy, strict=True)}}
                    for row in r.rows
                ],
                "truncated": r.truncated,
            }
        )
        return {"chart_id": chart_id, "points": len(r.rows)}

    # ----- dispatch -----

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run one tool. Errors become {"error": ...} so the model can correct itself."""
        step = Step(tool=name, args=args, summary="")
        try:
            out = await self._dispatch(name, args, step)
        except ToolError as exc:
            step.error = str(exc)
            step.summary = step.summary or "failed"
            out = {"error": str(exc)}
        except (KeyError, TypeError) as exc:
            step.error = f"Bad arguments: {exc}"
            out = {"error": step.error}
        self.state.steps.append(step)
        if "error" not in out:
            self.state.numbers += collect_numbers(out)
        return out

    async def _dispatch(self, name: str, a: dict[str, Any], step: Step) -> dict[str, Any]:
        if name == "get_schema":
            step.summary = f"Read the schema{' of ' + a['table'] if a.get('table') else ''}"
            return self.schema(a.get("table") or None)
        if name == "get_column_profile":
            step.summary = f"Read the profile of {a['table']}.{a['column']}"
            return self.column_profile(a["table"], a["column"])
        if name == "search_columns":
            step.summary = f"Searched columns for “{a['query']}”"
            return self.search(a["query"])
        if name == "run_sql":
            step.summary = str(a.get("purpose") or "Ran a query")
            step.query_id, out = await self.run_sql(a["sql"])
            return out
        if name == "run_stat_test":
            step.summary = f"Ran {a['test']} on {a['table']}.{a['x']} and {a['y']}"
            step.query_id, out = await self.stat_test(
                a["test"], a["table"], a["x"], a["y"], a.get("where")
            )
            step.result = {k: v for k, v in out.items() if k != "query_id"}
            return out
        if name == "make_chart":
            step.summary = f"Made a {a['type']} chart: {a['title']}"
            return self.chart(int(a["query_id"]), a["type"], a["x"], list(a["y"]), a["title"])
        raise ToolError(f"Unknown tool {name!r}.")


def _drop_keys(profile: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        k: _drop_keys(v, keys) if isinstance(v, dict) else v
        for k, v in profile.items()
        if k not in keys
    }
