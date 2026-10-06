"""Steps 1 and 2: parse a research question, then map its constructs to columns.

Both are LLM calls with structured output. The model sees the question, the research topic and
the schema (names, types, descriptions, statistics and masked frequent values), never rows.
Everything the model proposes is validated: unknown tables or columns are dropped, and SQL
fragments (derived expressions, population filters) must pass the SQL guard.
"""

import json
from pathlib import Path
from typing import Any

from api.agent.tools import WIDE_TABLE, ColumnInfo, ProjectContext
from api.ingest.names import quote
from api.llm.client import LLMClient
from api.rq.schemas import Candidate, MappedConstruct, Mapping, ParsedRQ
from api.semantic.column_retrieval import ColumnRetriever
from api.semantic.describer import column_evidence
from api.sql.guard import GuardError, check_sql

PROMPTS = Path(__file__).parent.parent / "prompts"
PARSE_VERSION = "rq_parse.v1"
MAP_VERSION = "rq_map.v1"
WIDE_KEEP = 40  # columns per wide table shown to the mapper


def _prompt(version: str) -> str:
    return (PROMPTS / f"{version}.md").read_text(encoding="utf-8")


async def parse(
    client: LLMClient, text: str, topic: str | None, project_id: int | None = None
) -> ParsedRQ:
    content = f"<research_question>\n{text}\n</research_question>"
    if topic:
        content = f"<topic>\n{topic}\n</topic>\n" + content
    result = await client.complete_structured(
        [
            {"role": "system", "content": _prompt(PARSE_VERSION)},
            {"role": "user", "content": content},
        ],
        ParsedRQ,
        step="rq_parse",
        prompt_version=PARSE_VERSION,
        project_id=project_id,
    )
    assert result.parsed is not None
    return result.parsed


def column_entry(c: ColumnInfo, share_samples: bool) -> dict[str, Any]:
    out = column_evidence(
        c.name, c.label, c.semantic_type, c.is_pii, c.profile or {}, share_samples
    )
    if out.get("header") == c.name:
        out.pop("header")
    if c.description:
        out["description"] = c.description
    return out


async def schema_for(
    ctx: ProjectContext, query: str, retriever: ColumnRetriever | None = None
) -> dict[str, Any]:
    """The schema shown to the mapper; wide tables keep only the most relevant columns."""
    retriever = retriever or ColumnRetriever()
    tables = []
    for t in ctx.tables:
        columns = t.columns
        note = None
        if len(columns) > WIDE_TABLE:
            ranked = await retriever.rank(query, [(t.table, c) for c in columns], WIDE_KEEP)
            keep = {id(r.column) for r in ranked}
            columns = [c for c in columns if id(c) in keep]
            note = f"{len(columns)} of {len(t.columns)} columns shown (most relevant)."
        entry: dict[str, Any] = {
            "table": t.table,
            "rows": t.rows,
            "columns": [column_entry(c, ctx.share_samples) for c in columns],
        }
        if note:
            entry["note"] = note
        tables.append(entry)
    return {"tables": tables}


async def map_constructs(
    client: LLMClient,
    ctx: ProjectContext,
    text: str,
    parsed: ParsedRQ,
    retriever: ColumnRetriever | None = None,
    project_id: int | None = None,
) -> tuple[Mapping, list[str]]:
    """Propose a mapping; returns it validated, with the problems that were removed."""
    query = text + " " + " ".join(c.name for c in parsed.constructs)
    schema = await schema_for(ctx, query, retriever)
    content = (
        f"<research_question>\n{text}\n</research_question>\n"
        f"<constructs>\n{json.dumps(parsed.model_dump(), ensure_ascii=False)}\n</constructs>\n"
        f"<schema>\n{json.dumps(schema, ensure_ascii=False, default=str)}\n</schema>"
    )
    result = await client.complete_structured(
        [{"role": "system", "content": _prompt(MAP_VERSION)}, {"role": "user", "content": content}],
        Mapping,
        step="rq_map",
        prompt_version=MAP_VERSION,
        project_id=project_id,
    )
    assert result.parsed is not None
    mapping = align(result.parsed, parsed)
    return validate(ctx, mapping)


def align(mapping: Mapping, parsed: ParsedRQ) -> Mapping:
    """One mapped construct per parsed construct, in order, whatever the model returned."""
    by_name = {c.name.strip().lower(): i for i, c in enumerate(mapping.constructs)}
    matched = [by_name.get(c.name.strip().lower()) for c in parsed.constructs]
    # Constructs the model renamed are matched by position, using only unclaimed entries.
    free = [i for i in range(len(mapping.constructs)) if i not in matched]
    constructs = []
    for i, c in enumerate(parsed.constructs):
        index = matched[i]
        if index is None and i < len(mapping.constructs) and i in free:
            index = i
            free.remove(i)
        found = mapping.constructs[index] if index is not None else None
        constructs.append(
            MappedConstruct(name=c.name, role=c.role, candidates=found.candidates if found else [])
        )
    return mapping.model_copy(update={"constructs": constructs})


def validate(ctx: ProjectContext, mapping: Mapping) -> tuple[Mapping, list[str]]:
    """Drop candidates and filters that do not refer to real columns or fail the SQL guard."""
    problems: list[str] = []
    names = [t.table for t in ctx.tables]
    constructs = []
    for mc in mapping.constructs:
        kept: list[Candidate] = []
        for cand in mc.candidates[:3]:
            fixed, problem = _check_candidate(ctx, cand, names)
            if problem:
                problems.append(f"{mc.name}: {problem}")
            elif fixed is not None:
                kept.append(fixed)
        status = mc.status
        if not kept and status == "confirmed":
            status = "proposed"
        constructs.append(mc.model_copy(update={"candidates": kept, "status": status}))

    population = mapping.population_filter
    primary = next((c.candidates[0].table for c in constructs if c.candidates), None)
    if population and population.strip():
        table = primary or names[0]
        try:
            check_sql(f"SELECT count(*) FROM {quote(table)} WHERE {population}", names)
        except GuardError as exc:
            problems.append(f"Population filter removed: {exc}")
            population = None
    else:
        population = None

    time_column = mapping.time_column
    if time_column:
        tables = [ctx.table(primary)] if primary else ctx.tables
        found = next(
            (c for t in tables for c in t.columns if c.name.lower() == time_column.lower()), None
        )
        if found is None:
            problems.append(f"Time column {time_column!r} not found; time scope ignored.")
            time_column = None
        else:
            time_column = found.name
    return (
        mapping.model_copy(
            update={
                "constructs": constructs,
                "population_filter": population,
                "time_column": time_column,
                "time_start": mapping.time_start if time_column else None,
                "time_end": mapping.time_end if time_column else None,
            }
        ),
        problems,
    )


def _check_candidate(
    ctx: ProjectContext, cand: Candidate, names: list[str]
) -> tuple[Candidate | None, str | None]:
    table = next((t for t in ctx.tables if t.table.lower() == cand.table.lower()), None)
    if table is None:
        return None, f"unknown table {cand.table!r}"
    if cand.match == "derivable":
        if not cand.expression:
            return None, "a derivable match needs an expression"
        try:
            check_sql(f"SELECT {cand.expression} FROM {quote(table.table)}", names)
        except GuardError as exc:
            return None, f"expression rejected: {exc}"
        return cand.model_copy(update={"table": table.table, "column": None}), None
    col = next(
        (c for c in table.columns if cand.column and c.name.lower() == cand.column.lower()), None
    )
    if col is None:
        return None, f"unknown column {cand.table}.{cand.column}"
    return cand.model_copy(update={"table": table.table, "column": col.name}), None
