"""Which papers relate to a research question, without an LLM.

A paper relates when the extracted cells that describe what it studies (problem, research
questions, approach, findings, results, title) share enough content words with the question
and its parsed constructs. The matching cells are returned, so each link shows the cited
sentences behind it.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from api.semantic.column_retrieval import STOP_WORDS

EXTRA_STOP = frozenset({
    "affect", "affects", "effect", "effects", "influence", "impact", "relationship", "between",
    "whether", "associated", "association", "difference", "differ", "compared", "among",
    "using", "use", "study", "studies", "paper", "data", "can", "more", "less", "higher",
    "lower", "into", "over", "under", "about", "after", "before", "during",
})  # fmt: skip
TOPIC_COLUMNS = (
    "problem_statement", "research_questions", "approach", "key_findings", "results",
    "conclusion", "datasets", "population", "intervention_or_exposure", "outcomes",
    "main_result", "main_contribution", "population_or_domain", "subjects",
)  # fmt: skip


def stem(word: str) -> str:
    """Fold plurals only ("grades" -> "grade", "studies" -> "study"): stripping more suffixes
    makes unrelated words collide and the same word stem differently."""
    word = word.strip("'")
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def terms(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9'\-]*[a-z0-9']|[a-z0-9]", text.lower())
    return {
        stem(w)
        for w in words
        if len(w) > 2 and w not in STOP_WORDS and w not in EXTRA_STOP and not w.isdigit()
    }


@dataclass
class Related:
    paper_id: int
    score: float
    matched_terms: list[str]
    cells: list[dict[str, Any]] = field(default_factory=list)  # column_key, terms


def question_terms(text: str, parsed: dict[str, Any] | None) -> set[str]:
    out = terms(text)
    for c in (parsed or {}).get("constructs", []):
        out |= terms(str(c.get("name", "")))
    if (parsed or {}).get("population"):
        out |= terms(str(parsed["population"]))  # type: ignore[index]
    return out


def related_papers(
    rq_terms: set[str],
    papers: Iterable[tuple[int, str | None]],
    cells: Sequence[Any],
    columns: dict[str, str],
) -> list[Related]:
    """Rank papers by the question terms their topic cells contain. `columns` maps the table's
    column keys to labels; only topic columns (and any non-metadata text column) count."""
    if not rq_terms:
        return []
    need = max(2, math.ceil(len(rq_terms) * 0.3))
    by_paper: dict[int, list[Any]] = {}
    for c in cells:
        if c.status in ("done", "unverified") and c.review != "rejected":
            by_paper.setdefault(c.paper_id, []).append(c)
    out = []
    for paper_id, title in papers:
        hits: dict[str, set[str]] = {}
        matched = terms(title or "") & rq_terms
        for c in by_paper.get(paper_id, []):
            if c.column_key not in columns or c.column_key not in TOPIC_COLUMNS:
                continue
            value = c.value_json
            text = "; ".join(map(str, value)) if isinstance(value, list) else str(value or "")
            found = terms(text) & rq_terms
            if found:
                hits[c.column_key] = found
                matched |= found
        if len(matched) >= need:
            out.append(
                Related(
                    paper_id,
                    round(len(matched) / len(rq_terms), 3),
                    sorted(matched),
                    [{"column_key": k, "terms": sorted(v)} for k, v in hits.items()],
                )
            )
    return sorted(out, key=lambda r: -r.score)
