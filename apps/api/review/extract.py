"""Fill one paper's row of a review table, with checked citations.

1. Metadata columns (title, authors, year, ...) come from the parsed PDF metadata when it is
   there, cited to the first-page passage that contains them. No AI call.
2. The other columns go to the LLM in one call with the paper's citable passages, each with its
   ID. Long papers send only the passages most relevant to each column, plus the abstract and
   conclusion, so cost stays bounded.
3. Each answer is checked without an LLM (`citations.check_cell`): unknown passage IDs are
   dropped, quotes must be in the cited passage, numbers must be in the cited text, categories
   must be one of the options. Cells that fail are sent back once with the problems listed;
   if they fail again they are kept but marked "unverified".
"""

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from api.llm.client import LLMClient
from api.review.citations import CellCheck, check_cell, normalise
from api.review.templates import TemplateColumn
from api.semantic.column_retrieval import Embed, cosine, words

log = logging.getLogger(__name__)

EXTRACT_VERSION = "review_extract.v1"
PROMPT = Path(__file__).resolve().parent.parent / "prompts" / f"{EXTRACT_VERSION}.md"
LONG_PAPER_CHARS = 60_000  # about 15,000 tokens of passages
PASSAGES_PER_COLUMN = 12
ALWAYS_SENT = ("abstract", "conclusion")


class PassageLike(Protocol):
    id: int
    ordinal: int
    label: str
    page: int
    text: str
    kind: str
    section_kind: str


class CitationIn(BaseModel):
    passage: str = Field(max_length=40)
    quote: str = Field(max_length=2000)


class CellIn(BaseModel):
    column: str
    found: bool
    value: str | float | list[str] | None = None
    citations: list[CitationIn] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] | None = None
    reason: str | None = None


class ExtractionOut(BaseModel):
    cells: list[CellIn]


@dataclass
class PaperInput:
    passages: Sequence[PassageLike]
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None


@dataclass
class CellResult:
    column_key: str
    status: str  # done | not_found | unverified | failed
    value: Any = None
    source: str = "llm"  # llm | metadata
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: str | None = None
    note: str | None = None


@dataclass
class Extraction:
    cells: list[CellResult]
    passages_sent: int = 0
    retried: list[str] = field(default_factory=list)  # column keys sent back once
    llm_calls: int = 0


async def extract(
    client: LLMClient | None,
    columns: Sequence[TemplateColumn],
    paper: PaperInput,
    *,
    project_id: int | None = None,
    embed: Embed | None = None,
    no_ai_reason: str = "No AI model is configured (LLM_API_KEY).",
    check: bool = True,
) -> Extraction:
    """Extract every column for one paper. `check=False` skips the citation check and retry
    (for experiment 8 of the plan)."""
    by_label = {p.label: p for p in paper.passages if p.kind != "reference"}
    results: dict[str, CellResult] = {}

    ask: list[TemplateColumn] = []
    for c in columns:
        meta = _from_metadata(c, paper, by_label)
        if meta is not None:
            results[c.key] = meta
        else:
            ask.append(c)

    out = Extraction(cells=[])
    if ask and client is None:
        for c in ask:
            results[c.key] = CellResult(c.key, "failed", note=no_ai_reason)
    elif ask:
        assert client is not None
        sent = await _select_passages(list(by_label.values()), ask, embed)
        out.passages_sent = len(sent)
        messages = [
            {"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
            {"role": "user", "content": _user_message(ask, sent, paper)},
        ]
        reply = await _call(client, messages, project_id)
        out.llm_calls += 1
        answers = {a.column: a for a in reply.parsed.cells} if reply.parsed else {}
        checked = {c.key: _judge(c, answers.get(c.key), by_label, check) for c in ask}

        failing = [c for c in ask if checked[c.key][1]] if check else []
        if failing:
            out.retried = [c.key for c in failing]
            fix = {c.key: checked[c.key][1] for c in failing}
            retry_messages = [
                *messages,
                {"role": "assistant", "content": reply.text},
                {"role": "user", "content": _fix_message(failing, fix)},
            ]
            try:
                again = await _call(client, retry_messages, project_id)
                out.llm_calls += 1
                second = {a.column: a for a in again.parsed.cells} if again.parsed else {}
                for c in failing:
                    if c.key in second:
                        result, problems = _judge(c, second[c.key], by_label, check)
                        if not problems or result.status == "not_found":
                            checked[c.key] = (result, problems)
            except Exception as exc:  # keep the first answer, marked unverified
                log.warning("review retry failed: %s", exc)

        for c in ask:
            result, problems = checked[c.key]
            if problems and result.status not in ("not_found", "failed"):
                result.status = "unverified"
                result.note = "Citation check failed: " + "; ".join(problems)
            results[c.key] = result

    out.cells = [results[c.key] for c in columns]
    return out


async def _call(client: LLMClient, messages: list[dict[str, str]], project_id: int | None) -> Any:
    return await client.complete_structured(
        messages,
        ExtractionOut,
        step="review_extract",
        prompt_version=EXTRACT_VERSION,
        project_id=project_id,
    )


def _user_message(columns: Sequence[TemplateColumn], passages: Sequence[PassageLike],
                  paper: PaperInput) -> str:  # fmt: skip
    cols = [
        {
            "key": c.key,
            "label": c.label,
            "instructions": c.instructions,
            "kind": c.kind,
            **({"options": c.options} if c.options else {}),
        }
        for c in columns
    ]
    lines = [f"[{p.label}] ({p.section_kind}) {p.text}" for p in passages]
    title = f' title="{_attr(paper.title)}"' if paper.title else ""
    return (
        f"<columns>\n{json.dumps(cols, ensure_ascii=False, indent=1)}\n</columns>\n"
        f"<paper{title}>\n" + "\n".join(lines) + "\n</paper>"
    )


def _attr(text: str) -> str:
    return text.replace('"', "'").replace("<", "(").replace(">", ")")[:300]


def _fix_message(columns: Sequence[TemplateColumn], problems: dict[str, list[str]]) -> str:
    items = [{"column": c.key, "problems": problems[c.key]} for c in columns]
    return (
        "<fix>\n" + json.dumps(items, ensure_ascii=False, indent=1) + "\n</fix>\n"
        "Some answers failed the citation check. Answer again for these columns only. Copy "
        "each quote exactly from the passage you cite, cite the passages every number comes "
        "from, or set found to false if the paper does not state it."
    )


# --- judging one answer ----------------------------------------------------------------------


def _judge(
    column: TemplateColumn, answer: CellIn | None, passages: dict[str, PassageLike], check: bool
) -> tuple[CellResult, list[str]]:
    if answer is None:
        return CellResult(column.key, "failed", note="The AI did not answer this column."), []
    value, problems = _coerce(column, answer.value) if answer.found else (None, [])
    if not answer.found or _empty(value):
        reason = (answer.reason or "").strip() or "The paper does not state this."
        return CellResult(column.key, "not_found", note=reason[:1000]), []

    cited = [(c.passage.strip().strip("[]"), c.quote) for c in answer.citations]
    result = CellResult(column.key, "done", value=value, confidence=answer.confidence, source="llm")
    if not check:
        result.citations = _unchecked(cited, passages)
        return result, problems
    verdict: CellCheck = check_cell(value, cited, passages)
    result.citations = [c.to_json() for c in verdict.citations]
    return result, problems + verdict.problems


def _unchecked(
    cited: list[tuple[str, str]], passages: dict[str, PassageLike]
) -> list[dict[str, Any]]:
    out = []
    for label, quote in cited:
        p = passages.get(label)
        if p is not None:
            out.append({"passage_id": p.id, "label": label, "page": p.page, "quote": quote,
                        "score": None, "verified": False})  # fmt: skip
    return out


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _coerce(column: TemplateColumn, value: Any) -> tuple[Any, list[str]]:
    """Bring a value into the column's kind. Returns the value and any problems."""
    if value is None:
        return None, []
    if column.kind == "list":
        if isinstance(value, list):
            items = [str(v).strip() for v in value]
        else:
            items = [s.strip() for s in re.split(r"\n|;\s", str(value))]
        return [i for i in items if i][:50], []
    if column.kind == "number":
        if isinstance(value, int | float):
            return float(value), []
        m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
        if m is None:
            return str(value), [f'"{value}" is not a number']
        return float(m.group(0).replace(",", "")), []
    if column.kind == "category":
        text = value[0] if isinstance(value, list) and value else str(value)
        for option in column.options:
            if normalise(option) == normalise(text):
                return option, []
        return text, [f'"{text}" is not one of the options: ' + ", ".join(column.options)]
    if isinstance(value, list):
        return "; ".join(str(v) for v in value), []
    if isinstance(value, float) and value.is_integer():
        return str(int(value)), []
    return str(value).strip(), []


# --- metadata columns ------------------------------------------------------------------------


def _from_metadata(
    column: TemplateColumn, paper: PaperInput, passages: dict[str, PassageLike]
) -> CellResult | None:
    if column.metadata is None:
        return None
    value: Any = getattr(paper, column.metadata)
    if _empty(value):
        return None
    if column.kind == "list" and not isinstance(value, list):
        value = [value]
    if column.kind == "number":
        value = float(value)
    if column.kind == "text" and isinstance(value, list):
        value = ", ".join(value)
    citations = _metadata_citations(column.metadata, value, passages)
    return CellResult(
        column.key,
        "done",
        value=value,
        source="metadata",
        citations=citations,
        confidence="high",
        note=None if citations else "From the PDF's metadata.",
    )


def _metadata_citations(
    field_name: str, value: Any, passages: dict[str, PassageLike]
) -> list[dict[str, Any]]:
    """Cite the first-page passage that contains the metadata value, when there is one."""
    first_page = [p for p in passages.values() if p.page == 1]
    if field_name == "authors":
        needles = [str(value[0])] if value else []
    elif field_name == "year":
        needles = [str(int(value))]
    else:
        needles = [str(value)]
    out = []
    for needle in needles:
        n = normalise(needle)
        for p in first_page:
            if n and n in normalise(p.text):
                quote = _span(p.text, needle)
                out.append({"passage_id": p.id, "label": p.label, "page": p.page,
                            "quote": quote, "score": 1.0, "verified": True})  # fmt: skip
                break
    return out


def _span(text: str, needle: str) -> str:
    i = text.lower().find(needle.lower())
    return text[i : i + len(needle)] if i >= 0 else needle


# --- choosing passages for long papers -------------------------------------------------------


async def _select_passages(
    passages: list[PassageLike], columns: Sequence[TemplateColumn], embed: Embed | None
) -> list[PassageLike]:
    if sum(len(p.text) for p in passages) <= LONG_PAPER_CHARS:
        return passages
    keep: set[int] = {p.ordinal for p in passages if p.section_kind in ALWAYS_SENT}
    vectors: list[list[float]] | None = None
    queries: list[list[float]] | None = None
    if embed is not None:
        try:
            vectors = await embed([p.text[:2000] for p in passages])
            queries = await embed([f"{c.label}: {c.instructions}" for c in columns])
        except Exception as exc:
            log.warning("passage embeddings failed, using word overlap: %s", exc)
            vectors = queries = None
    for i, c in enumerate(columns):
        query = words(f"{c.label} {c.instructions}")
        scored = []
        for j, p in enumerate(passages):
            heading = words(f"{p.section_kind.replace('_', ' ')} {getattr(p, 'section', '') or ''}")
            score = 0.1 * len(query & words(p.text)) + 0.3 * len(query & heading)
            if vectors is not None and queries is not None:
                score += cosine(queries[i], vectors[j])
            scored.append((score, p.ordinal))
        scored.sort(reverse=True)
        keep |= {o for _, o in scored[:PASSAGES_PER_COLUMN]}
    return [p for p in passages if p.ordinal in keep]
