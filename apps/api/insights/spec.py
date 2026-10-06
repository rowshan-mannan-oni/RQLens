"""An analysis to run: two columns of one table and a test from the fixed library.

Specs come from three places, in priority order: the research questions' column mappings,
the LLM planner, and the profile's strongest associations. Every spec is validated against the
schema and the test's column kinds before it runs; no generated code ever runs.
"""

from typing import Literal

from pydantic import BaseModel, Field

from api.agent.tools import ColumnInfo, ProjectContext, TableInfo
from api.rq.feasibility import kind_of

TestName = Literal["spearman", "mann_whitney", "kruskal_wallis", "chi_square", "trend"]
Source = Literal["rq", "llm", "profile"]

MAX_GROUPS = 20  # a grouping column with more distinct values is not used for group tests
ORDINAL_MIN = 6  # a numeric column typed categorical with this many values is treated as ordered


class AnalysisSpec(BaseModel):
    table: str
    test: TestName
    x: str = Field(description="First column (see the test's column order).")
    y: str = Field(description="Second column.")
    where: str | None = Field(default=None, max_length=1000, description="Optional SQL filter.")
    reason: str = Field(default="", max_length=300)
    rq_id: int | None = None
    source: Source = "llm"

    def key(self) -> tuple[str, frozenset[str]]:
        return self.table.lower(), frozenset({self.x.lower(), self.y.lower()})


class Plan(BaseModel):
    analyses: list[AnalysisSpec] = Field(max_length=20)


def column(table: TableInfo, name: str) -> ColumnInfo | None:
    return next((c for c in table.columns if c.name.lower() == name.lower()), None)


def distinct(c: ColumnInfo) -> int:
    return int((c.profile or {}).get("distinct") or 0)


def looks_like_row_id(c: ColumnInfo) -> bool:
    """A complete integer column with a different value in every row: a row number or ID.

    The profiler may type these numeric (CSV exports often carry a row-number column), but
    analysing them only reflects how the file was sorted.
    """
    p = c.profile or {}
    return "INT" in c.physical_type and p.get("uniqueness") == 1.0 and p.get("missing") == 0


def usable(c: ColumnInfo) -> bool:
    """Identifiers, constants, free text and personal data are never analysed."""
    if c.is_pii or looks_like_row_id(c):
        return False
    return (c.semantic_type or "") not in ("identifier", "constant", "free_text")


def is_number(c: ColumnInfo) -> bool:
    return any(t in c.physical_type for t in ("INT", "DOUBLE", "DECIMAL", "FLOAT", "REAL"))


def is_ordinal(c: ColumnInfo) -> bool:
    """Numbers the profiler typed categorical (few values), but with enough values to rank."""
    return kind_of(c) == "categorical" and is_number(c) and distinct(c) >= ORDINAL_MIN


def numeric_like(c: ColumnInfo) -> bool:
    return kind_of(c) == "numeric" or is_ordinal(c)


def is_grouping(c: ColumnInfo) -> bool:
    if is_ordinal(c):
        return False
    return kind_of(c) in ("categorical", "boolean") and 2 <= distinct(c) <= MAX_GROUPS


def choose_test(outcome: ColumnInfo, explanatory: ColumnInfo) -> tuple[TestName, str, str] | None:
    """The test for an (outcome, explanatory) pair, with the library's (x, y) column order."""
    on, en = numeric_like(outcome), numeric_like(explanatory)
    if kind_of(explanatory) == "datetime" and on:
        return "trend", explanatory.name, outcome.name
    if on and en:
        return "spearman", explanatory.name, outcome.name
    if on and is_grouping(explanatory):
        test: TestName = "mann_whitney" if distinct(explanatory) == 2 else "kruskal_wallis"
        return test, outcome.name, explanatory.name
    if en and is_grouping(outcome):
        test = "mann_whitney" if distinct(outcome) == 2 else "kruskal_wallis"
        return test, explanatory.name, outcome.name
    if is_grouping(outcome) and is_grouping(explanatory):
        return "chi_square", explanatory.name, outcome.name
    return None


def validate(ctx: ProjectContext, spec: AnalysisSpec) -> tuple[AnalysisSpec | None, str | None]:
    """The spec with canonical names, or the reason it cannot run."""
    table = next((t for t in ctx.tables if t.table.lower() == spec.table.lower()), None)
    if table is None:
        return None, f"unknown table {spec.table!r}"
    cx, cy = column(table, spec.x), column(table, spec.y)
    if cx is None or cy is None:
        return None, f"unknown column in {table.table}: {spec.x if cx is None else spec.y}"
    if cx.name == cy.name:
        return None, "the two columns are the same"
    if not usable(cx) or not usable(cy):
        return None, "identifier, constant, free-text or personal-data column"
    kx, ky = kind_of(cx), kind_of(cy)
    nx, ny = numeric_like(cx), numeric_like(cy)
    fits = {
        "spearman": nx and ny,
        "mann_whitney": nx and is_grouping(cy) and distinct(cy) == 2,
        "kruskal_wallis": nx and is_grouping(cy),
        "chi_square": is_grouping(cx) and is_grouping(cy),
        "trend": (kx == "datetime" or nx) and ny,
    }[spec.test]
    if not fits:
        return None, f"{spec.test} does not fit {cx.name} ({kx}) and {cy.name} ({ky})"
    return spec.model_copy(update={"table": table.table, "x": cx.name, "y": cy.name}), None
