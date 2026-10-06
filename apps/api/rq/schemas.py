"""Shapes for research-question fit: the parsed question, the column mapping, and the result.

The parse and mapping shapes double as the JSON schemas the LLM must return; their field
descriptions are part of the prompt.
"""

from typing import Literal

from pydantic import BaseModel, Field

RQType = Literal["descriptive", "comparative", "correlational", "predictive", "causal"]
Role = Literal["dependent", "independent", "covariate"]
Match = Literal["direct", "proxy", "derivable"]
Kind = Literal["numeric", "categorical", "datetime", "boolean", "text"]
Level = Literal["fail", "warn", "info", "pass"]
Verdict = Literal["answerable", "partial", "not_answerable"]

CORE_ROLES = ("dependent", "independent")


# ---- step 1: parse ----------------------------------------------------------------------


class Construct(BaseModel):
    name: str = Field(max_length=200, description="Short name, e.g. 'bug-fix time'.")
    role: Role = Field(
        description="dependent: the outcome, or what is described. independent: the "
        "explanatory or grouping variable. covariate: a control or context variable."
    )
    description: str = Field(default="", max_length=400)


class ParsedRQ(BaseModel):
    type: RQType
    population: str = Field(default="", max_length=400, description="Who or what is studied.")
    constructs: list[Construct] = Field(min_length=1, max_length=8)
    comparison: str | None = Field(
        default=None, max_length=400, description="Groups or conditions compared, if any."
    )
    time_scope: str | None = Field(default=None, max_length=200, description="Period, if any.")


# ---- step 2: map ------------------------------------------------------------------------


class Candidate(BaseModel):
    table: str
    column: str | None = Field(
        default=None, description="The column, for direct and proxy matches."
    )
    expression: str | None = Field(
        default=None,
        max_length=1000,
        description="For derivable matches: a DuckDB SQL expression over the table's columns.",
    )
    match: Match
    kind: Kind | None = Field(default=None, description="Data kind of the value.")
    justification: str = Field(default="", max_length=400)


class MappedConstruct(BaseModel):
    name: str
    role: Role
    candidates: list[Candidate] = Field(
        default_factory=list, description="Best first. Empty when nothing in the data fits."
    )
    # proposed: from the model; confirmed: accepted or edited by the user; rejected: the user
    # says no candidate fits (the construct is treated as a gap).
    status: Literal["proposed", "confirmed", "rejected"] = "proposed"


class Mapping(BaseModel):
    constructs: list[MappedConstruct]
    population_filter: str | None = Field(
        default=None,
        max_length=1000,
        description="DuckDB SQL condition selecting the population, or null for all rows.",
    )
    time_column: str | None = Field(default=None, description="Date column for the time scope.")
    time_start: str | None = Field(default=None, description="ISO date, inclusive.")
    time_end: str | None = Field(default=None, description="ISO date, inclusive.")
    notes: str = Field(default="", max_length=600)


# ---- steps 3 and 4: measure and decide --------------------------------------------------


class RuleResult(BaseModel):
    rule: str
    level: Level
    message: str
    query_id: int | None = None
    values: dict[str, object] = Field(default_factory=dict)


class Writeup(BaseModel):
    """What the LLM writes after the verdict is decided."""

    explanation: str = Field(max_length=1500, description="Two to four sentences.")
    suggested_method: str = Field(max_length=600)
    threats: list[str] = Field(default_factory=list, max_length=6)
    rewording: str | None = Field(
        default=None,
        max_length=600,
        description="A version of the question the data can answer; null if not needed.",
    )


class Suggestion(BaseModel):
    text: str = Field(max_length=400)
    type: RQType
    columns: list[str] = Field(description="table.column names the question would use.")
    reason: str = Field(default="", max_length=300)


class Suggestions(BaseModel):
    suggestions: list[Suggestion] = Field(max_length=6)
