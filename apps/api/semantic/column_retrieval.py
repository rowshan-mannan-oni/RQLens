"""Find the columns relevant to a question, for tables too wide to show in full.

Columns are ranked by word overlap with their name, header and description, plus, when an
embedding model is available, the cosine similarity between the question and an embedding of
the column's header, name, type and description. Embeddings find columns by meaning ("cost"
finds `sale_price`); word overlap keeps exact name matches on top. Without embeddings, ranking
falls back to word overlap alone.

Column embeddings are cached in memory by text, so each column is embedded once per process
until its description changes.
"""

import hashlib
import logging
import math
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

# texts -> one vector per text
Embed = Callable[[Sequence[str]], Awaitable[list[list[float]]]]

CACHE_SIZE = 50_000
EMBED_BATCH = 100  # providers cap inputs per request
WORD_WEIGHT = 0.1  # one matching word in the name adds this much to a cosine similarity
NAME_WORD_POINTS = 3
DESCRIPTION_WORD_POINTS = 1
PREFIX_POINTS = 1


class ColumnLike(Protocol):
    name: str
    label: str | None
    semantic_type: str | None
    description: str | None


@dataclass(frozen=True)
class Ranked:
    table: str
    column: ColumnLike
    score: float
    words: int  # word-overlap points
    similarity: float | None  # cosine similarity, when embeddings were used


STOP_WORDS = frozenset({
    "the", "of", "in", "on", "at", "to", "for", "by", "with", "and", "or", "a", "an", "is", "are",
    "was", "were", "be", "been", "what", "which", "who", "how", "many", "much", "did", "do",
    "does", "has", "have", "had", "per", "from", "as", "that", "this", "these", "those", "than",
    "its", "their", "there", "it", "any", "all", "each",
})  # fmt: skip


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in STOP_WORDS}


def word_points(query: set[str], column: ColumnLike) -> int:
    name_words = words(f"{column.name} {column.label or ''}")
    desc_words = words(column.description or "")
    points = NAME_WORD_POINTS * len(query & name_words)
    points += DESCRIPTION_WORD_POINTS * len(query & desc_words)
    points += PREFIX_POINTS * sum(1 for w in query if any(n.startswith(w) for n in name_words))
    return points


def column_text(column: ColumnLike) -> str:
    label = column.label if column.label and column.label != column.name else ""
    head = f"{label} ({column.name})" if label else column.name
    kind = f" [{column.semantic_type}]" if column.semantic_type else ""
    return f"{head}{kind}: {column.description or ''}".strip()


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class ColumnRetriever:
    def __init__(self, embed: Embed | None = None) -> None:
        self.embed = embed
        self.failed = False  # set after an embedding error; later calls use words only

    async def rank(
        self, query: str, columns: Sequence[tuple[str, ColumnLike]], limit: int
    ) -> list[Ranked]:
        """The `limit` best columns for `query`. Without embeddings, only columns sharing a word
        with the query are returned."""
        q = words(query)
        points = [word_points(q, c) for _, c in columns]
        similarities = await self._similarities(query, [c for _, c in columns])
        ranked = [
            Ranked(
                table=t,
                column=c,
                score=(s + WORD_WEIGHT * p) if s is not None else float(p),
                words=p,
                similarity=s,
            )
            for (t, c), p, s in zip(columns, points, similarities, strict=True)
            if s is not None or p > 0
        ]
        ranked.sort(key=lambda r: -r.score)
        return ranked[:limit]

    async def _similarities(self, query: str, columns: Sequence[ColumnLike]) -> list[float | None]:
        if self.embed is None or self.failed or not columns:
            return [None] * len(columns)
        texts = [column_text(c) for c in columns]
        try:
            vectors = await _embed_cached(self.embed, [query, *texts], cache_from=1)
        except Exception as exc:  # the provider may not offer embeddings; words still work
            log.warning("column embeddings unavailable: %s", exc)
            self.failed = True
            return [None] * len(columns)
        question, column_vectors = vectors[0], vectors[1:]
        return [cosine(question, v) for v in column_vectors]


_cache: OrderedDict[str, list[float]] = OrderedDict()


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _embed_cached(embed: Embed, texts: list[str], *, cache_from: int) -> list[list[float]]:
    """Embed texts, reusing cached vectors for texts[cache_from:] (the question is not cached)."""
    out: list[list[float] | None] = [None] * len(texts)
    missing: list[int] = []
    for i, text in enumerate(texts):
        hit = _cache.get(_key(text)) if i >= cache_from else None
        if hit is None:
            missing.append(i)
        else:
            out[i] = hit
    if missing:
        vectors: list[list[float]] = []
        for start in range(0, len(missing), EMBED_BATCH):
            batch = [texts[i] for i in missing[start : start + EMBED_BATCH]]
            got = await embed(batch)
            if len(got) != len(batch):
                raise ValueError("The embedding service returned the wrong number of vectors.")
            vectors += got
        for i, v in zip(missing, vectors, strict=True):
            out[i] = v
            if i >= cache_from:
                _cache[_key(texts[i])] = v
                while len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
    return [v for v in out if v is not None]


def clear_cache() -> None:
    _cache.clear()
