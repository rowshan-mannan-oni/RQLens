"""The sample project: its bundled data loads and its questions get the intended verdicts."""

from itertools import count
from pathlib import Path

from api import samples
from api.rq.pipeline import assess
from api.rq.schemas import Mapping, ParsedRQ
from api.sql.executor import QueryResult, run_query
from evals import local_project


def test_bundled_csv_matches_the_versioned_dataset() -> None:
    versioned = local_project.DATASETS / "penguins" / "v1" / "penguins.csv"
    assert samples.SAMPLE_CSV.read_bytes() == versioned.read_bytes()


async def test_sample_questions_without_an_ai_model(tmp_path: Path) -> None:
    db = tmp_path / "sample.duckdb"
    ctx = local_project.build(db, ["penguins"])
    ids = count(1)

    async def execute(sql: str, limit: int) -> tuple[int, QueryResult]:
        return next(ids), run_query(db, sql, ["penguins"], row_limit=limit)

    verdicts = []
    for q in samples.QUESTIONS:
        a = await assess(
            None,
            ctx,
            q["text"],
            execute,
            parsed=ParsedRQ.model_validate(q["parsed"]),
            mapping=Mapping.model_validate(q["mapping"]),
        )
        assert a.problems == [] and a.explained_by == "rules"
        verdicts.append(a.verdict)
    assert verdicts == ["answerable", "answerable", "not_answerable"]
