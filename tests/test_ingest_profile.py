"""Loader and profiler against small CSVs whose expected numbers were worked out by hand."""

from pathlib import Path
from typing import Any

import duckdb
import pytest

from api.ingest.loader import load_csv
from api.ingest.names import sanitize_identifier
from api.profiler.tables import DatasetProfile, profile_table

SURVEY = """\
respondent_id;Age (yrs);Gender;Income;Joined;Score;zip
1;34;F;52000;2024-01-01;4;02139
2;N/A;M;-999;2024-01-08;5;10001
3;29;F;48000;2024-01-15;4;02139
4;41;F;-999;2024-01-22;3;94105
5;38;F;61000;2024-01-29;4;10001
6;45;F;58000;2024-02-12;4;02139
7;52;F;75000;2024-02-19;5;94105
8;33;F;50000;2024-02-26;2;10001
9;27;F;47000;2024-03-04;4;02139
10;36;F;55000;2024-03-11;4;60601
11;30;F;50000;2024-03-18;4;02139;EXTRA
"""


def run(tmp_path: Path, content: bytes | str, name: str = "t") -> DatasetProfile:
    path = tmp_path / f"{name}.csv"
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    con = duckdb.connect()
    return profile_table(con, load_csv(con, path, name))


def col(result: DatasetProfile, name: str) -> dict[str, Any]:
    return next(r.profile for r in result.columns if r.column.name == name)


def codes(result: DatasetProfile, column: str | None = None) -> set[str]:
    return {w["code"] for w in result.warnings if column is None or w["column"] == column}


@pytest.fixture
def survey(tmp_path: Path) -> DatasetProfile:
    return run(tmp_path, SURVEY, "survey")


def test_load(survey: DatasetProfile) -> None:
    assert survey.table["row_count"] == 10  # the row with an extra field is rejected
    assert "rejected_rows" in codes(survey)
    names = [(r.column.name, r.column.original_name) for r in survey.columns]
    assert names[1] == ("age_yrs", "Age (yrs)")
    # Leading zeros keep zip codes as text.
    assert col(survey, "zip")["physical_type"] == "VARCHAR"


def test_semantic_types(survey: DatasetProfile) -> None:
    types = {r.column.name: r.profile["semantic_type"] for r in survey.columns}
    assert types == {
        "respondent_id": "identifier",
        "age_yrs": "numeric",
        "gender": "categorical",
        "income": "numeric",
        "joined": "datetime",
        "score": "categorical",
        "zip": "categorical",
    }
    assert survey.table["candidate_keys"] == ["respondent_id"]


def test_numeric_profile(survey: DatasetProfile) -> None:
    age = col(survey, "age_yrs")
    assert (age["missing"], age["non_null"]) == (1, 9)
    assert age["numeric"]["min"] == 27 and age["numeric"]["max"] == 52
    assert age["numeric"]["median"] == 36
    assert sum(b["count"] for b in age["numeric"]["histogram"]) == 9

    income = col(survey, "income")["numeric"]
    assert income["quantiles"]["p25"] == pytest.approx(47250)
    assert income["quantiles"]["p75"] == pytest.approx(57250)
    assert income["negatives"] == 2
    assert income["sentinels"] == [{"value": -999.0, "count": 2}]
    assert "placeholder_value" in codes(survey, "income")


def test_categorical_profile(survey: DatasetProfile) -> None:
    gender = col(survey, "gender")
    assert gender["top_values"][0] == {"value": "F", "count": 9, "share": 0.9}
    assert gender["categorical"]["imbalance_ratio"] == 9
    assert "imbalance" in codes(survey, "gender")


def test_datetime_profile(survey: DatasetProfile) -> None:
    joined = col(survey, "joined")["datetime"]
    assert joined["granularity"] == "weekly"
    assert joined["period"] == "week"
    assert len(joined["counts"]) == 11  # 2024-01-01 .. 2024-03-11
    assert joined["empty_periods"] == 1  # week of 2024-02-05
    assert "date_gaps" in codes(survey, "joined")


def test_text_column_with_stray_value_is_retyped(tmp_path: Path) -> None:
    rows = "\n".join(str(i) for i in range(1, 60))
    result = run(tmp_path, f"amount\n{rows}\nn.a.\n")
    amount = col(result, "amount")
    assert amount["physical_type"] == "BIGINT"
    assert amount["missing"] == 1
    coerced = next(w for w in result.warnings if w["code"] == "coerced_values")
    assert coerced["details"] == {"count": 1, "examples": ["n.a."]}


def test_latin1_duplicates_constant_missing(tmp_path: Path) -> None:
    content = "name,grp,flag\nJosé,a,x\nJosé,a,x\nRenée,b,x\nZoë,c,\n".encode("latin-1")
    result = run(tmp_path, content)
    assert "encoding_fallback" in codes(result)
    assert col(result, "name")["top_values"][0]["value"] == "José"
    assert result.table["duplicate_rows"] == 1
    assert "duplicate_rows" in codes(result)
    assert {"constant", "high_missing"} <= codes(result, "flag")


def test_sanitize_identifier() -> None:
    taken: set[str] = set()
    assert sanitize_identifier("Age (yrs)", taken) == "age_yrs"
    assert sanitize_identifier("age yrs", taken) == "age_yrs_2"
    assert sanitize_identifier("2024 score", taken) == "col_2024_score"
    assert sanitize_identifier("___", taken) == "col"
    assert sanitize_identifier('x"; DROP TABLE t; --', taken) == "x_drop_table_t"
    assert sanitize_identifier("Années d'études", taken) == "annees_d_etudes"
    assert sanitize_identifier("Âge", taken) == "age"


def test_columns_named_like_internal_aliases(tmp_path: Path) -> None:
    # Regression: the profiler groups by aliases such as v, n and p; data columns with those
    # names must not shadow them.
    header = "v,n,p,u,x,k,b,r,lo,hi,day"
    rows = "\n".join(
        f"{i % 3},{i % 4},{i % 5},{i},{i * 2},{i % 2},{i % 6},{i % 7},{i},{i},"
        f"2024-01-{1 + i % 28:02d}"
        for i in range(60)
    )
    result = run(tmp_path, f"{header}\n{rows}\n")
    assert result.table["row_count"] == 60
    assert col(result, "v")["top_values"][0]["count"] == 20
    assert sum(p["count"] for p in col(result, "day")["datetime"]["counts"]) == 60
