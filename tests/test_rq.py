"""Research-question fit: verdict rules, feasibility checks on real datasets, mapping validation,
and the whole pipeline with a scripted LLM."""

import json
from itertools import count
from pathlib import Path
from typing import Any

import httpx2
import pytest

from api.agent.tools import ProjectContext
from api.llm.client import LLMClient
from api.llm.tracing import TraceRecord
from api.rq import mapper
from api.rq.feasibility import measure
from api.rq.pipeline import assess
from api.rq.schemas import Candidate, MappedConstruct, Mapping, ParsedRQ
from api.rq.verdict import (
    ConstructStatus,
    Measurements,
    apply_rules,
    decide,
    margin_of_error,
    min_detectable_d,
    min_detectable_r,
)
from api.sql.executor import QueryResult, run_query
from evals import local_project

# ---- verdict rules on synthetic measurements ---------------------------------------------


def base(**overrides: Any) -> Measurements:
    m = Measurements(
        rq_type="comparative",
        constructs=[
            ConstructStatus("wage", "dependent", "direct", "t"),
            ConstructStatus("union", "independent", "direct", "t"),
        ],
        total_rows=500,
        rows_in_scope=500,
        complete_cases=500,
        needs_groups=True,
        groups=[("no", 400), ("yes", 100)],
        outcome_distinct=200,
        outcome_top_share=0.05,
    )
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def fired(m: Measurements) -> dict[str, str]:
    return {r.rule: r.level for r in apply_rules(m)}


def test_clean_comparison_is_answerable() -> None:
    assert fired(base()) == {}
    assert decide(apply_rules(base())) == "answerable"


@pytest.mark.parametrize(
    ("overrides", "rule", "verdict"),
    [
        (
            {"constructs": [ConstructStatus("wage", "dependent", None)]},
            "core_gap",
            "not_answerable",
        ),
        ({"rows_in_scope": 0}, "no_rows_in_scope", "not_answerable"),
        ({"complete_cases": 9}, "too_few_complete", "not_answerable"),
        ({"outcome_distinct": 1}, "outcome_constant", "not_answerable"),
        ({"groups": [("no", 495), ("yes", 4)]}, "too_few_groups", "not_answerable"),
        ({"time_coverage": 0.0}, "no_time_overlap", "not_answerable"),
        ({"complete_cases": 29}, "small_sample", "partial"),
        ({"groups": [("no", 480), ("yes", 19)]}, "small_group", "partial"),
        ({"groups": [("no", 1100), ("yes", 100)]}, "unbalanced_groups", "partial"),
        ({"outcome_top_share": 0.96}, "outcome_near_constant", "partial"),
        ({"time_coverage": 0.5}, "partial_time_coverage", "partial"),
        ({"rq_type": "causal"}, "causal_claim", "partial"),
    ],
)
def test_each_rule(overrides: dict[str, Any], rule: str, verdict: str) -> None:
    m = base(**overrides)
    assert rule in fired(m)
    assert decide(apply_rules(m)) == verdict


def test_mapping_rules() -> None:
    m = base(
        constructs=[
            ConstructStatus("wage", "dependent", "proxy", "t", missing_share=0.4),
            ConstructStatus("union", "independent", "direct", "t"),
            ConstructStatus("tenure", "covariate", None),
            ConstructStatus("region", "covariate", "direct", "other_table"),
        ]
    )
    assert fired(m) == {
        "proxy_only": "warn",
        "covariate_gap": "warn",
        "multi_table": "warn",
        "high_missing": "warn",
    }


def test_power_formulas_match_textbook_sample_sizes() -> None:
    # Cohen: 64 per group detects d = 0.5; 85 rows detect r = 0.3 (80% power, alpha 0.05).
    assert min_detectable_d(64, 64) == pytest.approx(0.495, abs=0.005)
    assert min_detectable_r(85) == pytest.approx(0.30, abs=0.005)
    assert margin_of_error(100) == pytest.approx(0.098, abs=0.001)


def test_low_power_rules() -> None:
    assert fired(base(groups=[("a", 400), ("b", 12), ("c", 12)]))["low_power"] == "warn"
    corr = base(needs_groups=False, groups=None, correlational=True, complete_cases=25)
    assert fired(corr)["low_power"] == "warn"
    desc = base(rq_type="descriptive", needs_groups=False, groups=None, complete_cases=40)
    assert fired(desc)["low_power"] == "warn"
    assert "low_power" not in fired(base(complete_cases=5000, groups=[("a", 2500), ("b", 2500)]))


def test_power_is_skipped_once_a_fail_rule_fired() -> None:
    assert "low_power" not in fired(base(complete_cases=5, groups=[("a", 3), ("b", 2)]))


def test_messages_quote_measured_numbers() -> None:
    (rule,) = apply_rules(base(complete_cases=17))
    assert "17" in rule.message


# ---- feasibility on the development datasets ---------------------------------------------


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, ProjectContext]:
    db = tmp_path_factory.mktemp("rq") / "dev.duckdb"
    ctx = local_project.build(db, ["penguins", "titanic", "flights", "taxis"])
    return db, ctx


def executor(db: Path, ctx: ProjectContext) -> Any:
    ids = count(1)
    tables = [t.table for t in ctx.tables]

    async def execute(sql: str, row_limit: int) -> tuple[int, QueryResult]:
        return next(ids), run_query(db, sql, tables, row_limit=row_limit)

    return execute


def mc(
    name: str, role: str, table: str, column: str | None, match: str = "direct", **kw: Any
) -> MappedConstruct:
    if column is None and "expression" not in kw:
        return MappedConstruct(name=name, role=role, candidates=[])
    return MappedConstruct(
        name=name,
        role=role,
        candidates=[Candidate(table=table, column=column, match=match, **kw)],
    )


async def run_case(project: tuple[Path, ProjectContext], parsed: ParsedRQ, mapping: Mapping) -> Any:
    db, ctx = project
    mapping, problems = mapper.validate(ctx, mapping)
    assert problems == []
    report = await measure(ctx, parsed, mapping, executor(db, ctx))
    assert report.errors == []
    rules = apply_rules(report.measurements)
    return report, {r.rule for r in rules}, decide(rules)


async def test_penguins_species_comparison(project: Any) -> None:
    parsed = ParsedRQ(
        type="comparative",
        constructs=[
            {"name": "body mass", "role": "dependent"},
            {"name": "species", "role": "independent"},
        ],
    )
    mapping = Mapping(
        constructs=[
            mc("body mass", "dependent", "penguins", "body_mass_g"),
            mc("species", "independent", "penguins", "species"),
        ],
        population_filter="species IN ('Adelie', 'Gentoo')",
    )
    report, rules, verdict = await run_case(project, parsed, mapping)
    m = report.measurements
    # Hand-checked: 344 penguins, 276 Adelie or Gentoo, 2 of them without body mass.
    assert (m.total_rows, m.rows_in_scope, m.complete_cases) == (344, 276, 274)
    assert m.groups == [("Adelie", 151), ("Gentoo", 123)]
    assert verdict == "answerable", rules
    assert set(m.query_ids) >= {"rows", "missing", "outcome", "groups"}


async def test_missing_construct_is_not_answerable(project: Any) -> None:
    parsed = ParsedRQ(
        type="correlational",
        constructs=[
            {"name": "diet", "role": "independent"},
            {"name": "body mass", "role": "dependent"},
        ],
    )
    mapping = Mapping(
        constructs=[
            mc("diet", "independent", "penguins", None),
            mc("body mass", "dependent", "penguins", "body_mass_g"),
        ]
    )
    _, rules, verdict = await run_case(project, parsed, mapping)
    assert "core_gap" in rules and verdict == "not_answerable"


async def test_constant_outcome_in_scope(project: Any) -> None:
    parsed = ParsedRQ(type="descriptive", constructs=[{"name": "species", "role": "dependent"}])
    mapping = Mapping(
        constructs=[mc("species", "dependent", "penguins", "species")],
        population_filter="island = 'Torgersen'",
    )
    _, rules, verdict = await run_case(project, parsed, mapping)
    assert "outcome_constant" in rules and verdict == "not_answerable"  # only Adelie there


async def test_time_scope_outside_the_data(project: Any) -> None:
    parsed = ParsedRQ(type="descriptive", constructs=[{"name": "passengers", "role": "dependent"}])
    base_map = Mapping(
        constructs=[mc("passengers", "dependent", "flights", "passengers")], time_column="year"
    )
    outside = base_map.model_copy(update={"time_start": "1970-01-01", "time_end": "1979-12-31"})
    _, rules, verdict = await run_case(project, parsed, outside)
    assert {"no_rows_in_scope", "no_time_overlap"} <= rules and verdict == "not_answerable"

    partly = base_map.model_copy(update={"time_start": "1955-01-01", "time_end": "1965-12-31"})
    report, rules, verdict = await run_case(project, parsed, partly)
    assert report.measurements.rows_in_scope == 72  # 1955 to 1960, 12 months each
    assert "partial_time_coverage" in rules and verdict == "partial"


async def test_causal_question_with_class_groups(project: Any) -> None:
    parsed = ParsedRQ(
        type="causal",
        constructs=[
            {"name": "survival", "role": "dependent"},
            {"name": "ticket class", "role": "independent"},
        ],
    )
    mapping = Mapping(
        constructs=[
            mc("survival", "dependent", "titanic", "survived"),
            mc("ticket class", "independent", "titanic", "pclass"),
        ]
    )
    report, rules, verdict = await run_case(project, parsed, mapping)
    # pclass holds 1, 2, 3; the profiler types it categorical, so it splits rows into groups.
    assert report.measurements.groups == [("3", 491), ("1", 216), ("2", 184)]
    assert rules == {"causal_claim"} and verdict == "partial"


async def test_derived_construct_and_proxy(project: Any) -> None:
    parsed = ParsedRQ(
        type="comparative",
        constructs=[
            {"name": "tip rate", "role": "dependent"},
            {"name": "payment method", "role": "independent"},
        ],
    )
    mapping = Mapping(
        constructs=[
            mc(
                "tip rate",
                "dependent",
                "taxis",
                None,
                "derivable",
                expression="tip / NULLIF(fare, 0)",
                kind="numeric",
            ),
            mc("payment method", "independent", "taxis", "payment", "proxy"),
        ]
    )
    report, rules, verdict = await run_case(project, parsed, mapping)
    names = [g for g, _ in report.measurements.groups or []]
    assert names == ["credit card", "cash"]
    assert "proxy_only" in rules and verdict == "partial"


async def test_broken_expression_becomes_a_gap(project: Any) -> None:
    db, ctx = project
    parsed = ParsedRQ(type="descriptive", constructs=[{"name": "x", "role": "dependent"}])
    mapping = Mapping(
        constructs=[
            mc(
                "x",
                "dependent",
                "penguins",
                None,
                "derivable",
                expression="no_such_column * 2",
                kind="numeric",
            )
        ]
    )
    report = await measure(ctx, parsed, mapping, executor(db, ctx))
    assert report.errors and "core_gap" in {r.rule for r in apply_rules(report.measurements)}


# ---- mapping validation ------------------------------------------------------------------


def test_validate_drops_unknown_columns_and_unsafe_sql(project: Any) -> None:
    _, ctx = project
    mapping = Mapping(
        constructs=[
            MappedConstruct(
                name="mass",
                role="dependent",
                candidates=[
                    Candidate(table="PENGUINS", column="Body_Mass_G", match="direct"),
                    Candidate(table="penguins", column="weight", match="direct"),
                    Candidate(
                        table="penguins", expression="1; DROP TABLE penguins", match="derivable"
                    ),
                ],
            ),
            MappedConstruct(
                name="file",
                role="independent",
                candidates=[
                    Candidate(
                        table="penguins", expression="read_csv('/etc/passwd')", match="derivable"
                    ),
                ],
            ),
        ],
        population_filter="species = 'Adelie' OR 1 = (SELECT count(*) FROM read_parquet('x'))",
        time_column="nope",
    )
    fixed, problems = mapper.validate(ctx, mapping)
    first = fixed.constructs[0].candidates
    assert [(c.table, c.column) for c in first] == [("penguins", "body_mass_g")]
    assert fixed.constructs[1].candidates == []
    assert fixed.population_filter is None and fixed.time_column is None
    assert len(problems) == 5


def test_align_keeps_parsed_constructs_in_order() -> None:
    parsed = ParsedRQ(
        type="comparative",
        constructs=[{"name": "A", "role": "dependent"}, {"name": "B", "role": "independent"}],
    )
    mapping = Mapping(
        constructs=[
            MappedConstruct(
                name="b",
                role="dependent",
                candidates=[Candidate(table="t", column="x", match="direct")],
            )
        ]
    )
    aligned = mapper.align(mapping, parsed)
    assert [(c.name, c.role, len(c.candidates)) for c in aligned.constructs] == [
        ("A", "dependent", 0),
        ("B", "independent", 1),
    ]


# ---- the whole pipeline with a scripted LLM ----------------------------------------------


def completion(content: str) -> dict[str, Any]:
    return {
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
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def scripted_client(replies: list[Any]) -> tuple[LLMClient, list[Any]]:
    requests: list[Any] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        reply = replies.pop(0)
        if isinstance(reply, int):
            return httpx2.Response(reply, json={"error": {"message": "down"}})
        return httpx2.Response(200, json=completion(json.dumps(reply)))

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
    return client, requests


PARSE = {
    "type": "comparative",
    "population": "penguins",
    "constructs": [
        {"name": "flipper length", "role": "dependent"},
        {"name": "species", "role": "independent"},
    ],
}
MAP = {
    "constructs": [
        {
            "name": "flipper length",
            "role": "dependent",
            "candidates": [
                {
                    "table": "penguins",
                    "column": "flipper_length_mm",
                    "match": "direct",
                    "kind": "numeric",
                    "justification": "Flipper length in mm.",
                }
            ],
        },
        {
            "name": "species",
            "role": "independent",
            "candidates": [
                {
                    "table": "penguins",
                    "column": "species",
                    "match": "direct",
                    "kind": "categorical",
                    "justification": "Species name.",
                }
            ],
        },
    ],
    "population_filter": None,
}


async def test_pipeline_end_to_end(project: Any) -> None:
    db, ctx = project
    explain_bad = {
        "explanation": "Answerable: 999 rows.",
        "suggested_method": "Kruskal-Wallis.",
        "threats": [],
        "rewording": "x",
    }
    explain_ok = {
        "explanation": "Answerable: 342 complete rows across 3 species.",
        "suggested_method": "Kruskal-Wallis test with epsilon squared.",
        "threats": ["Two penguins have no measurements."],
        "rewording": "unneeded",
    }
    client, requests = scripted_client([PARSE, MAP, explain_bad, explain_ok])
    text = "Does flipper length differ between penguin species?"
    a = await assess(client, ctx, text, executor(db, ctx))

    assert a.verdict == "answerable"
    assert a.explained_by == "llm" and a.grounding == {"ok": True, "checked": 1, "unsupported": []}
    assert a.writeup.rewording is None  # dropped for answerable questions
    assert "999" in requests[3]["messages"][-1]["content"]  # the rejected number was sent back
    assert "<research_question>" in requests[0]["messages"][1]["content"]
    assert len(a.query_ids) >= 4
    # The schema the mapper saw has statistics and frequent values, not rows.
    assert '"frequent_values"' in requests[1]["messages"][1]["content"]


async def test_pipeline_keeps_the_verdict_when_explaining_fails(project: Any) -> None:
    db, ctx = project
    client, _ = scripted_client([500])
    mapping = Mapping.model_validate(MAP)
    a = await assess(
        client, ctx, "q", executor(db, ctx), parsed=ParsedRQ.model_validate(PARSE), mapping=mapping
    )
    assert a.verdict == "answerable"
    assert a.explained_by == "rules" and a.writeup.explanation.startswith("The data looks able")
