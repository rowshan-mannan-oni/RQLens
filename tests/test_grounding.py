"""Grounding check: numbers in answers must come from tool results."""

import pytest

from api.agent.grounding import check, collect_numbers, extract_claims


def texts(answer: str) -> list[str]:
    return [c.text for c in extract_claims(answer)]


def test_extraction_skips_code_dates_identifiers_and_small_counts() -> None:
    answer = (
        "The top 3 groups in `col_42` (Q3, wave_2) on 2024-03-15 had a mean of 42.3 and n = 1,204."
    )
    assert texts(answer) == ["42.3", "1,204"]


def test_extraction_reads_percent_scale_sign_and_bounds() -> None:
    claims = extract_claims("rho = -0.21, 45% of 1.2 million rows, p < 0.001, 7%")
    assert [(c.value, c.percent, c.scale, c.bound) for c in claims] == [
        (-0.21, False, 1.0, None),
        (45.0, True, 1.0, None),
        (1.2, False, 1e6, None),
        (0.001, False, 1.0, "<"),
        (7.0, True, 1.0, None),
    ]


def test_sentence_end_period_is_not_a_decimal() -> None:
    assert texts("The median was 12.") == ["12"]


@pytest.mark.parametrize(
    ("answer", "pool"),
    [
        ("The mean is 42.3.", [42.3147]),
        ("The mean is 42.", [41.6]),
        ("45% are women.", [0.4512]),
        ("45.1% are women.", [45.1234]),
        ("About 1.2 million rows.", [1_234_567]),
        ("There are 1,204 rows.", [1204]),
        ("p < 0.001", [0.00002]),
        ("It fell by 3.5 points.", [-3.48]),
        ("Values reached 2024.", ["2024-01-01"]),
    ],
)
def test_supported(answer: str, pool: list[object]) -> None:
    result = check(answer, collect_numbers(pool))
    assert result.ok, result.unsupported


@pytest.mark.parametrize(
    ("answer", "pool"),
    [
        ("The mean is 42.3.", [42.4]),
        ("45% are women.", [0.47]),
        ("p < 0.001", [0.04]),
        ("There are 1,205 rows.", [1204]),
    ],
)
def test_unsupported(answer: str, pool: list[object]) -> None:
    result = check(answer, collect_numbers(pool))
    assert not result.ok
    assert result.checked == 1


def test_collect_numbers_walks_nested_values() -> None:
    pool = collect_numbers({"rows": [[1, "a 2.5 b"], [None, True]], "x": {"y": -3}})
    assert sorted(pool) == [-3.0, 1.0, 2.5]
