"""Insights: spec validation, test choice, ranking, confounder check, the whole pipeline on real
and planted data, and LLM rewrites held to the grounding check."""

import csv
import json
import random
from itertools import count
from pathlib import Path
from typing import Any

import httpx2
import pytest

from api.agent.tools import ColumnInfo, ProjectContext, TableInfo
from api.ingest.pipeline import run_load, run_pii, run_profile
from api.insights import planner
from api.insights.pipeline import Question, generate
from api.insights.ranking import magnitude, rank
from api.insights.runner import Outcome
from api.insights.spec import AnalysisSpec, choose_test, validate
from api.insights.writer import rewrite
from api.llm.client import LLMClient
from api.llm.tracing import TraceRecord
from api.rq.schemas import Candidate, MappedConstruct, Mapping
from api.sql.executor import QueryResult, run_query
from api.stats.library import TestResult as StatResult
from evals import local_project

# ---- specs and test choice ---------------------------------------------------------------


def col(name: str, kind: str, distinct: int = 100, pii: bool = False) -> ColumnInfo:
    physical = {"numeric": "DOUBLE", "datetime": "DATE"}.get(kind, "VARCHAR")
    return ColumnInfo(name, None, physical, kind, None, None, None, pii, {"distinct": distinct})


CTX = ProjectContext(
    1,
    None,
    True,
    [
        TableInfo(
            "t",
            "t.csv",
            100,
            [
                col("score", "numeric"),
                col("age", "numeric"),
                col("group2", "categorical", 2),
                col("group4", "categorical", 4),
                col("city", "categorical", 300),
                col("when", "datetime"),
                col("id", "identifier"),
                col("email", "categorical", 5, pii=True),
                ColumnInfo(
                    "bugs", None, "BIGINT", "categorical", None, None, None, False, {"distinct": 9}
                ),
                ColumnInfo(
                    "level", None, "BIGINT", "categorical", None, None, None, False, {"distinct": 3}
                ),
                ColumnInfo(
                    "row_no",
                    None,
                    "BIGINT",
                    "numeric",
                    None,
                    None,
                    None,
                    False,
                    {"distinct": 100, "uniqueness": 1.0, "missing": 0},
                ),
            ],
        )
    ],
)
T = CTX.tables[0]


def c(name: str) -> ColumnInfo:
    found = next(x for x in T.columns if x.name == name)
    return found


@pytest.mark.parametrize(
    ("outcome", "explanatory", "expected"),
    [
        ("score", "age", ("spearman", "age", "score")),
        ("score", "group2", ("mann_whitney", "score", "group2")),
        ("score", "group4", ("kruskal_wallis", "score", "group4")),
        ("group4", "age", ("kruskal_wallis", "age", "group4")),
        ("group2", "group4", ("chi_square", "group4", "group2")),
        ("score", "when", ("trend", "when", "score")),
        ("score", "city", None),  # too many groups
        ("score", "bugs", ("spearman", "bugs", "score")),  # ordered counts, not groups
        ("score", "level", ("kruskal_wallis", "score", "level")),  # 3 numeric codes are groups
    ],
)
def test_choose_test(outcome: str, explanatory: str, expected: Any) -> None:
    assert choose_test(c(outcome), c(explanatory)) == expected


@pytest.mark.parametrize(
    ("spec", "problem"),
    [
        (AnalysisSpec(table="t", test="spearman", x="score", y="id"), "identifier"),
        (AnalysisSpec(table="t", test="spearman", x="score", y="row_no"), "identifier"),
        (AnalysisSpec(table="t", test="chi_square", x="email", y="group2"), "personal"),
        (AnalysisSpec(table="t", test="spearman", x="score", y="group4"), "does not fit"),
        (AnalysisSpec(table="t", test="mann_whitney", x="score", y="group4"), "does not fit"),
        (AnalysisSpec(table="t", test="spearman", x="score", y="nope"), "unknown column"),
        (AnalysisSpec(table="x", test="spearman", x="score", y="age"), "unknown table"),
        (AnalysisSpec(table="t", test="spearman", x="score", y="SCORE"), "same"),
    ],
)
def test_validate_rejects(spec: AnalysisSpec, problem: str) -> None:
    checked, reason = validate(CTX, spec)
    assert checked is None and problem in (reason or "")


def test_combine_deduplicates_pairs_and_aliases() -> None:
    specs = [
        AnalysisSpec(table="T", test="spearman", x="Score", y="age", source="rq"),
        AnalysisSpec(table="t", test="spearman", x="age", y="score"),  # same pair, reversed
        AnalysisSpec(table="t", test="kruskal_wallis", x="score", y="group4"),
        AnalysisSpec(table="t", test="mann_whitney", x="score", y="group2"),  # alias of group4
    ]
    alias = planner.aliases({"t": [{"a": "group2", "b": "group4", "value": 0.99}]})
    plan, dropped = planner.combine(CTX, specs, alias=alias)
    assert [(s.x, s.y, s.source) for s in plan] == [
        ("score", "age", "rq"),
        ("score", "group4", "llm"),
    ]
    assert dropped == []


# ---- ranking -----------------------------------------------------------------------------


def outcome(p: float, effect: float, n: int, source: str = "profile", name: str = "rho") -> Outcome:
    spec = AnalysisSpec(table="t", test="spearman", x="a", y=f"b{p}{effect}", source=source)
    return Outcome(spec, StatResult("spearman", "rho", effect, p, name, effect, n))


def test_magnitude_labels() -> None:
    assert [magnitude("rho", v) for v in (0.05, 0.2, 0.4, -0.7)] == [
        "negligible",
        "small",
        "medium",
        "large",
    ]
    assert magnitude("epsilon_squared", 0.07) == "medium"


def test_rank_uses_adjusted_p_relevance_and_effect_not_p_alone() -> None:
    tiny_p_tiny_effect = outcome(1e-12, 0.05, 100_000)
    rq_medium = outcome(0.001, 0.35, 300, source="rq")
    borderline = outcome(0.04, 0.3, 200)  # significant alone, not after correction
    ranked = rank([tiny_p_tiny_effect, borderline, rq_medium], set())
    assert ranked[0].outcome is rq_medium
    by = {id(r.outcome): r for r in ranked}
    assert by[id(tiny_p_tiny_effect)].status == "weak"
    assert by[id(borderline)].p_adjusted == pytest.approx(0.04)  # 0.04 * 3 / 3
    assert by[id(borderline)].status == "finding"
    ranked = rank([borderline, outcome(0.5, 0.0, 100), outcome(0.6, 0.0, 100)], set())
    assert {r.status for r in ranked} == {"no_evidence"}  # 0.04 * 3 = 0.12 after correction


def test_mapped_columns_raise_relevance() -> None:
    a, b = outcome(0.001, 0.3, 500), outcome(0.001, 0.3, 500)
    a.spec = a.spec.model_copy(update={"x": "mapped_col"})
    ranked = rank([a, b], {("t", "mapped_col")})
    assert ranked[0].outcome is a and ranked[0].relevance == 0.6


# ---- planted data ------------------------------------------------------------------------


def build(tmp: Path, name: str, header: list[str], rows: list[list[Any]]) -> tuple[Path, Any]:
    path = tmp / f"{name}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    db = tmp / "planted.duckdb"
    report = run_load(db, path, name)
    profile = run_profile(db, report)
    pii = run_pii(db, profile, name)
    ctx = ProjectContext(
        1,
        None,
        True,
        [
            TableInfo(
                name,
                path.name,
                report.row_count,
                [
                    ColumnInfo(
                        r.column.name,
                        r.column.original_name,
                        r.column.physical_type,
                        r.profile["semantic_type"],
                        None,
                        None,
                        None,
                        pii[r.column.name].is_pii,
                        r.profile,
                    )
                    for r in profile.columns
                ],
            )
        ],
    )
    assoc = {name: profile.table["relationships"]["associations"]}
    return db, (ctx, assoc)


def executor(db: Path, tables: list[str]) -> Any:
    ids = count(1)

    async def execute(sql: str, limit: int) -> tuple[int, QueryResult]:
        return next(ids), run_query(db, sql, tables, row_limit=limit)

    return execute


def mapping(table: str, outcome_col: str, explanatory: str) -> Mapping:
    return Mapping(
        constructs=[
            MappedConstruct(
                name="outcome",
                role="dependent",
                candidates=[Candidate(table=table, column=outcome_col, match="direct")],
            ),
            MappedConstruct(
                name="cause",
                role="independent",
                candidates=[Candidate(table=table, column=explanatory, match="direct")],
            ),
        ]
    )


async def test_planted_effect_ranks_first_and_noise_shows_no_evidence(tmp_path: Path) -> None:
    rng = random.Random(7)
    rows = []
    for _ in range(1500):
        treated = rng.random() < 0.5
        noise = [round(rng.gauss(0, 1), 4) for _ in range(6)]
        outcome_value = round(rng.gauss(0.8 if treated else 0.0, 1), 4)
        rows.append(["yes" if treated else "no", outcome_value, *noise])
    header = ["treated", "recovery", *[f"noise_{i}" for i in range(6)]]
    db, (ctx, assoc) = build(tmp_path, "trial", header, rows)
    # The profile reports only associations >= 0.1; add the noise pairs so they get tested.
    assoc["trial"] += [
        {"a": f"noise_{i}", "b": "recovery", "measure": "spearman", "value": 0.12} for i in range(6)
    ]
    g = await generate(
        ctx,
        executor(db, ["trial"]),
        questions=[
            Question(1, "Does treatment improve recovery?", mapping("trial", "recovery", "treated"))
        ],
        associations=assoc,
    )
    top = g.insights[0]
    assert (top.rq_id, top.status, top.spec and top.spec["test"]) == (1, "finding", "mann_whitney")
    noise = [x for x in g.insights if x.spec and "noise" in x.spec["x"] + x.spec["y"]]
    assert len(noise) == 6
    assert all(x.status == "no_evidence" for x in noise)
    assert all(x.grounding and x.grounding["ok"] for x in g.insights)
    assert all("Exploratory" in x.caveats[0] for x in g.insights)


async def test_confounder_check_finds_simpsons_paradox(tmp_path: Path) -> None:
    rng = random.Random(3)
    rows = []
    for dept, base in (("a", 0), ("b", 10), ("c", 20)):
        for _ in range(200):
            dose = base + rng.uniform(0, 10)
            # Within a department, more dose means lower response; departments differ by a lot.
            response = 5 * base - 2 * (dose - base) + rng.gauss(0, 2)
            rows.append([dept, round(dose, 3), round(response, 3)])
    db, (ctx, assoc) = build(tmp_path, "clinic", ["dept", "dose", "response"], rows)
    g = await generate(
        ctx,
        executor(db, ["clinic"]),
        questions=[
            Question(1, "Is dose associated with response?", mapping("clinic", "response", "dose"))
        ],
        associations=assoc,
    )
    top = g.insights[0]
    assert top.spec and (top.spec["x"], top.spec["y"]) == ("dose", "response")
    assert top.result and top.result["effect_size"] > 0  # positive overall
    checks = top.result["confounders"]
    assert [(c["column"], c["verdict"]) for c in checks] == [("dept", "reverses")]
    assert any("reverses within some groups of dept" in c for c in top.caveats)


# ---- real data and the LLM steps ---------------------------------------------------------


async def test_generate_on_penguins_with_data_quality(tmp_path: Path) -> None:
    db = tmp_path / "p.duckdb"
    ctx, assoc = local_project.build_with_associations(db, ["penguins"])
    rules = [
        {
            "rule": "high_missing",
            "level": "warn",
            "message": "“sex” is missing in 3% of rows.",
            "query_id": 7,
        }
    ]
    q = Question(
        1, "Do species differ in body mass?", mapping("penguins", "body_mass_g", "species"), rules
    )
    g = await generate(ctx, executor(db, ["penguins"]), questions=[q], associations=assoc)
    analyses = [x for x in g.insights if x.kind == "analysis"]
    assert 1 <= len(analyses) <= 20 and g.failed == []
    assert analyses[0].rq_id == 1 and "body_mass_g differs across species" in analyses[0].statement
    assert all(x.grounding and x.grounding["ok"] for x in analyses)
    assert all(x.chart and x.chart["data"] for x in analyses)
    dq = [x for x in g.insights if x.kind == "data_quality"]
    assert [(x.rq_id, x.query_ids) for x in dq] == [(1, [7])]


async def test_llm_rewrites_must_pass_grounding() -> None:
    requests: list[Any] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        content = json.dumps(
            {
                "statements": [
                    {
                        "index": 0,
                        "statement": "Gentoo are heavier (epsilon squared = 0.66, n = 342).",
                    },
                    {
                        "index": 1,
                        "statement": "Bigger flippers, about 12% heavier birds (rho = 0.87).",
                    },
                ]
            }
        )
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    async def tracer(record: TraceRecord) -> None:
        return None

    client = LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        tracer=tracer,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)),
    )
    items = [
        {"title": "a", "statement": "draft", "result": {"effect_size": 0.658, "n": 342}},
        {"title": "b", "statement": "draft", "result": {"effect_size": 0.871, "n": 342}},
    ]
    out = await rewrite(client, items)
    assert set(out) == {0}  # the second invented "12%"
    assert "<insights>" in requests[0]["messages"][1]["content"]
