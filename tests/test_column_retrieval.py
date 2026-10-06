"""Column retrieval for wide tables: word overlap, embeddings, caching and fallback."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest

from api.agent.tools import ColumnInfo, ProjectContext, TableInfo, ToolBox
from api.llm.client import LLMClient
from api.llm.tracing import TraceRecord
from api.semantic.column_retrieval import (
    EMBED_BATCH,
    ColumnRetriever,
    clear_cache,
    column_text,
)
from api.sql.executor import QueryResult

# A toy embedding: one dimension per concept, so similar meanings share a direction.
CONCEPTS = {
    "money": {"cost", "costs", "price", "sale", "expensive", "dollars", "paid"},
    "size": {"area", "size", "big", "sf", "square", "living"},
    "time": {"year", "built", "old", "age", "when", "construction"},
    "rooms": {"bedroom", "bedrooms", "rooms", "abvgr"},
}


def toy_vector(text: str) -> list[float]:
    words = set(text.lower().replace("_", " ").replace("(", " ").replace(")", " ").split())
    return [float(len(words & ws)) + 0.01 for ws in CONCEPTS.values()]


@dataclass
class FakeEmbed:
    calls: list[list[str]]
    fail: bool = False

    async def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("no embeddings here")
        self.calls.append(list(texts))
        return [toy_vector(t) for t in texts]


def col(name: str, description: str | None = None, kind: str = "numeric") -> ColumnInfo:
    return ColumnInfo(name, None, "BIGINT", kind, description, "llm", "high", False, {})


COLUMNS = [
    col("sale_price", "Sale price of the house in dollars"),
    col("gr_liv_area", "Above-ground living area in square feet"),
    col("year_built", "Original construction year"),
    col("bedroom_abvgr", "Number of bedrooms above ground"),
    col("ms_zoning", "Zoning classification", "categorical"),
]


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    clear_cache()


async def test_embeddings_find_columns_by_meaning() -> None:
    columns = [("ames", c) for c in COLUMNS]
    question = "How much did the expensive homes cost?"
    # No word in the question appears in any column: word matching finds nothing.
    assert await ColumnRetriever().rank(question, columns, 3) == []

    ranked = await ColumnRetriever(FakeEmbed([])).rank(question, columns, 3)
    assert ranked[0].column.name == "sale_price"
    assert ranked[0].similarity is not None


async def test_name_words_break_ties_and_rank_first() -> None:
    columns = [("ames", c) for c in COLUMNS]
    ranked = await ColumnRetriever(FakeEmbed([])).rank("year built", columns, 2)
    assert ranked[0].column.name == "year_built"
    assert ranked[0].words > 0


async def test_column_vectors_are_cached_and_the_question_is_not() -> None:
    embed = FakeEmbed([])
    retriever = ColumnRetriever(embed)
    columns = [("ames", c) for c in COLUMNS]
    await retriever.rank("price", columns, 3)
    await retriever.rank("size", columns, 3)
    assert len(embed.calls[0]) == 1 + len(COLUMNS)
    assert embed.calls[1] == ["size"]


async def test_large_tables_are_embedded_in_batches() -> None:
    embed = FakeEmbed([])
    columns = [("wide", col(f"c{i}", f"measure {i}")) for i in range(EMBED_BATCH + 20)]
    await ColumnRetriever(embed).rank("measure", columns, 5)
    assert [len(c) for c in embed.calls] == [EMBED_BATCH, 21]


async def test_falls_back_to_words_when_embeddings_fail() -> None:
    retriever = ColumnRetriever(FakeEmbed([], fail=True))
    ranked = await retriever.rank("sale price", [("ames", c) for c in COLUMNS], 3)
    assert [r.column.name for r in ranked] == ["sale_price"]
    assert ranked[0].similarity is None
    assert retriever.failed


def test_column_text_includes_header_type_and_description() -> None:
    c = ColumnInfo("q1", "Q1: How satisfied?", "BIGINT", "numeric", "Satisfaction 1-5", None,
                   None, False, {})  # fmt: skip
    assert column_text(c) == "Q1: How satisfied? (q1) [numeric]: Satisfaction 1-5"


async def test_wide_table_schema_shows_relevant_columns() -> None:
    filler = [col(f"extra_{i}", f"unrelated measure {i}") for i in range(60)]
    ctx = ProjectContext(1, None, True, [TableInfo("ames", "ames.csv", 10, [*filler, *COLUMNS])])

    async def execute(sql: str, row_limit: int) -> tuple[int, QueryResult]:
        raise AssertionError("not called")

    box = ToolBox(ctx, execute, ColumnRetriever(FakeEmbed([])))
    await box.prepare("What do expensive houses cost?")
    entry = box.schema()["tables"][0]
    assert entry["relevant_columns"][0]["name"] == "sale_price"
    assert entry["relevant_columns"][0]["description"].startswith("Sale price")
    assert len(entry["columns"]) == 65  # every column is still listed by name

    out = await box.call("search_columns", {"query": "how big is the house"})
    assert out["matches"][0]["name"] == "gr_liv_area"


async def test_llm_client_embed_is_traced() -> None:
    requests: list[Any] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append(body)
        data = [
            {"object": "embedding", "index": i, "embedding": [float(i), 1.0]}
            for i in reversed(range(len(body["input"])))
        ]
        usage = {"prompt_tokens": 12, "total_tokens": 12}
        return httpx2.Response(
            200, json={"object": "list", "data": data, "model": "e", "usage": usage}
        )

    traces: list[TraceRecord] = []

    async def tracer(record: TraceRecord) -> None:
        traces.append(record)

    client = LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        tracer=tracer,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)),
        embedding_model="e",
    )
    vectors = await client.embed(["a", "b"], step="column_retrieval", project_id=3)
    assert vectors == [[0.0, 1.0], [1.0, 1.0]]  # reordered by index
    assert (requests[0]["model"], requests[0]["input"]) == ("e", ["a", "b"])
    assert traces[0].input_tokens == 12 and traces[0].project_id == 3
    assert traces[0].request_json == {"model": "e", "inputs": 2}  # texts are not stored
