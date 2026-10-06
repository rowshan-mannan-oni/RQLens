"""Check citations against the paper, without an LLM.

A citation is a passage ID plus a short quote. It is verified when the quote appears in the
cited passage: exactly, after normalising case, whitespace, quotes, dashes and hyphenation, or
with a fuzzy match at or above FUZZY_THRESHOLD (small differences from PDF extraction). A quote
may run across adjacent cited passages, such as a sentence split by a page break.

A cell's value is also checked like a chat answer: every number in it must appear in the text
of a verified cited passage.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Protocol

from api.agent.grounding import collect_numbers, extract_claims, supported

FUZZY_THRESHOLD = 0.9
MIN_FUZZY_CHARS = 20  # shorter quotes must match exactly

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = {
    **dict.fromkeys(map(ord, "\u2018\u2019\u201a\u201b\u2032"), "'"),
    **dict.fromkeys(map(ord, "\u201c\u201d\u201e\u201f\u2033"), '"'),
}


class PassageLike(Protocol):
    id: int
    ordinal: int
    label: str
    page: int
    text: str


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_QUOTES)
    text = text.replace("\u00ad", "").lower()
    text = re.sub(r"-\s+", "", text)  # hyphenated line breaks that survived extraction
    text = text.replace("-", "")  # "cross-project" and "crossproject" compare equal
    text = re.sub(r"[\"'`]", "", text)
    return re.sub(r"\s+", " ", text).strip(" .")


def quote_score(quote: str, passage: str) -> float:
    """1.0 for an exact (normalised) match; otherwise the best fuzzy similarity of the quote
    against a window of the passage of the same length."""
    q, p = normalise(quote), normalise(passage)
    if not q:
        return 0.0
    if q in p:
        return 1.0
    if len(q) < MIN_FUZZY_CHARS or len(p) < len(q) * 0.8:
        return 0.0
    best = 0.0
    starts = [0] + [m.end() for m in re.finditer(r" ", p)]
    for s in starts:
        window = p[s : s + len(q) + 5]
        if len(window) < len(q) * 0.8:
            break
        ratio = SequenceMatcher(None, q, window, autojunk=False).ratio()
        best = max(best, ratio)
        if best >= 0.99:
            break
    return round(best, 3)


@dataclass
class CitationCheck:
    passage_id: int | None
    label: str
    page: int | None
    quote: str
    score: float
    verified: bool
    problem: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "passage_id": self.passage_id,
            "label": self.label,
            "page": self.page,
            "quote": self.quote,
            "score": self.score,
            "verified": self.verified,
            **({"problem": self.problem} if self.problem else {}),
        }


@dataclass
class CellCheck:
    citations: list[CitationCheck]
    unsupported_numbers: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.citations) and not self.problems


def check_cell(
    value: Any,
    cited: Sequence[tuple[str, str]],
    passages: Mapping[str, PassageLike],
    *,
    require_citation: bool = True,
) -> CellCheck:
    """Check a cell value and its citations [(label, quote)] against the paper's passages."""
    checks: list[CitationCheck] = []
    problems: list[str] = []
    known = [passages[label] for label, _ in cited if label in passages]
    for label, quote in cited:
        p = passages.get(label)
        if p is None:
            problems.append(f"{label} is not a passage of this paper")
            continue
        score = quote_score(quote, p.text)
        if score < 1.0:
            # The quote may continue into the next or previous cited passage.
            joined = _adjacent_text(p, known)
            if joined is not None:
                score = max(score, quote_score(quote, joined))
        verified = score >= FUZZY_THRESHOLD
        problem = None if verified else f'the quote "{quote[:120]}" is not in {label}'
        if problem:
            problems.append(problem)
        checks.append(CitationCheck(p.id, label, p.page, quote, score, verified, problem))

    if require_citation and not checks:
        problems.append("no citation was given")

    pool = collect_numbers([passages[c.label].text for c in checks])
    unsupported = [c.text for c in extract_claims(_value_text(value)) if not supported(c, pool)]
    if unsupported:
        problems.append(
            "these numbers are not in the cited passages: " + ", ".join(dict.fromkeys(unsupported))
        )
    return CellCheck(checks, list(dict.fromkeys(unsupported)), problems)


def _adjacent_text(p: PassageLike, cited: Sequence[PassageLike]) -> str | None:
    by_ordinal = {c.ordinal: c for c in cited}
    run = [p]
    o = p.ordinal - 1
    while o in by_ordinal:
        run.insert(0, by_ordinal[o])
        o -= 1
    o = p.ordinal + 1
    while o in by_ordinal:
        run.append(by_ordinal[o])
        o += 1
    return " ".join(x.text for x in run) if len(run) > 1 else None


def _value_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
