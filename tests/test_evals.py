"""Evaluation harness: execution-match scoring, BH correction, and an oracle run."""

import asyncio
from pathlib import Path

import pytest

from api.agent.loop import Limits
from api.stats.corrections import benjamini_hochberg
from evals import local_project
from evals.oracle import OracleClient
from evals.run_eval import load_cases, run_case
from evals.scoring import results_match, stat_results_match, values_match


@pytest.mark.parametrize(
    ("agent", "gold", "ok"),
    [
        (52.3, 52.31415, True),  # rounded in SQL to the precision shown
        (52.0, 52.31415, False),
        (5076.016, 5076.016260162602, True),
        (1, 1.0, True),
        ("Gentoo", "gentoo", True),
        (True, 1, True),
        (None, None, True),
        (None, 0, False),
    ],
)
def test_values_match(agent: object, gold: object, ok: bool) -> None:
    assert values_match(agent, gold) is ok


def test_extra_columns_and_column_order_are_allowed() -> None:
    gold = [["Adelie", 152], ["Gentoo", 124]]
    agent = [[124, "Gentoo", 36.0], [152, "Adelie", 44.2]]
    assert results_match(agent, gold)
    assert not results_match(agent, gold, order_matters=True)


def test_missing_rows_or_wrong_values_fail() -> None:
    gold = [["Adelie", 152], ["Gentoo", 124]]
    assert not results_match([["Adelie", 152]], gold)
    assert not results_match([["Adelie", 152], ["Gentoo", 125]], gold)
    assert not results_match([["Adelie"], ["Gentoo"]], gold)


def test_stat_results_match() -> None:
    gold = {"test": "mann_whitney", "p_value": 0.0012, "effect_size": 0.21}
    assert stat_results_match({**gold, "p_value": 0.00121, "effect_size": -0.215}, gold)
    assert not stat_results_match({**gold, "test": "kruskal_wallis"}, gold)
    assert not stat_results_match({**gold, "effect_size": 0.3}, gold)
    tiny = {"test": "spearman", "p_value": 1e-40, "effect_size": 0.9}
    assert stat_results_match({**tiny, "p_value": 3e-38}, tiny)


def test_benjamini_hochberg_matches_hand_calculation() -> None:
    # Sorted p: 0.01, 0.02, 0.03, 0.04 with m = 4: p * m / rank = 0.04, 0.04, 0.04, 0.04.
    assert benjamini_hochberg([0.04, 0.01, 0.03, 0.02]) == pytest.approx([0.04] * 4)
    # Monotone: a larger raw p never gets a smaller adjusted p; capped at 1.
    adjusted = benjamini_hochberg([0.001, 0.5, 0.9, 0.012])
    assert adjusted == pytest.approx([0.004, 0.6666667, 0.9, 0.024])
    assert benjamini_hochberg([]) == []


def test_oracle_passes_cases_on_the_real_datasets(tmp_path: Path) -> None:
    """The harness end to end: real loader, profiler, agent loop, guard, executor, scoring."""
    cases = load_cases(
        ["penguins-02", "penguins-03", "penguins-05", "ambiguous-01", "flights-03", "join-01"]
    )
    db = tmp_path / "eval.duckdb"
    names = sorted({t for c in cases for t in c["tables"]})
    ctx = local_project.build(db, names)
    client = OracleClient()

    async def run_all() -> list[dict[str, object]]:
        return [await run_case(client, db, ctx, c, Limits()) for c in cases]

    results = asyncio.run(run_all())
    assert [r["reason"] for r in results if not r["passed"]] == []
    assert all(r["grounded"] for r in results if r["kind"] == "answer")


def test_question_ids_are_unique_and_sql_cases_have_gold() -> None:
    cases = load_cases()
    assert len({c["id"] for c in cases}) == len(cases) >= 30
    for c in cases:
        assert (c["gold_sql"] is None) == (c["expected"] != "answer"), c["id"]
