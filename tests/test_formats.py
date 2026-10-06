import datetime as dt
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from api.ingest.formats import file_kind, load_file

FIXTURES = Path(__file__).parent / "fixtures" / "formats"


@pytest.fixture
def con():
    c = duckdb.connect()
    yield c
    c.close()


def rows(con, table):
    return con.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()


def types(con, table):
    return {r[0]: r[1] for r in con.execute(f'DESCRIBE "{table}"').fetchall()}


def test_file_kind():
    assert file_kind("a.CSV") == "csv"
    assert file_kind("a.xlsx") == "excel"
    assert file_kind("survey.sav") == file_kind("s.zsav") == file_kind("s.por") == "spss"
    assert file_kind("x.dta") == "stata"
    assert file_kind("x.parquet") == "parquet"
    assert file_kind("x.xls") is None and file_kind("x.pdf") is None


def test_spss_labels_codes_and_user_missing(con):
    report = load_file(con, FIXTURES / "survey.sav", "survey", "spss")
    t = types(con, "survey")
    ints = ("INTEGER", "BIGINT")
    assert t["id"] in ints and t["age"] in ints
    assert t["sex"] == "VARCHAR"  # every code labelled: stored as labels
    assert t["satisf"] in ints  # only the ends labelled: numbers kept
    assert t["visit"] == "DATE"
    data = rows(con, "survey")
    assert [r[1] for r in data] == ["Male", "Female", "Female", "Male", "Female", None]
    assert [r[3] for r in data] == [4, 5, 3, None, 2, 4]  # 99 = Don't know -> missing
    assert report.descriptions["sex"] == "Sex of respondent"
    assert report.descriptions["satisf"] == (
        "Satisfaction with care (1-5). Codes: 1 = Very low; 5 = Very high; 99 = Don't know"
    )
    kinds = {w["code"]: w["message"] for w in report.warnings}
    assert "'sex' (1: 9 = Refused)" in kinds["user_missing"]
    assert "'satisf' (1: 99 = Don't know)" in kinds["user_missing"]
    assert "'sex'" in kinds["value_labels"]


def test_stata(con):
    report = load_file(con, FIXTURES / "survey.dta", "s", "stata")
    data = rows(con, "s")
    assert [r[1] for r in data] == ["Male", "Female", "Female", "Male", "Female", "Refused"]
    assert report.descriptions["age"] == "Age in years"
    assert report.row_count == 6


def test_excel_first_sheet_header_types_and_errors(con, tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append([])
    ws.append(["Name", "Score", "Joined", "Mixed", None])
    ws.append(["Ana", 3.0, dt.datetime(2024, 1, 2), "12", "x"])
    ws.append(["Ben", 4.5, dt.datetime(2024, 3, 4), 13, None])
    ws.append(["Cy", "#DIV/0!", None, 14.0, None])
    wb.create_sheet("Notes").append(["just notes"])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    report = load_file(con, path, "book", "excel")
    t = types(con, "book")
    assert list(t) == ["name", "score", "joined", "mixed", "column4"]
    assert t["score"] == "DOUBLE" and t["joined"] == "DATE"
    assert t["mixed"] in ("INTEGER", "BIGINT")  # "12", 13, 14.0 -> re-typed as numbers
    assert rows(con, "book")[2][1] is None  # Excel error value -> missing
    assert any(w["code"] == "other_sheets" and "'Notes'" in w["message"] for w in report.warnings)


def test_parquet(con, tmp_path):
    path = tmp_path / "t.parquet"
    con.execute(
        f"COPY (SELECT 1 AS \"Patient ID\", [1, 2] AS tags, 'a' AS g) TO '{path}' (FORMAT parquet)"
    )
    report = load_file(con, path, "pq", "parquet")
    assert [c.name for c in report.columns] == ["patient_id", "tags", "g"]
    assert types(con, "pq")["tags"] == "VARCHAR"
    assert rows(con, "pq") == [(1, "[1, 2]", "a")]
