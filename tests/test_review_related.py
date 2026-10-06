from types import SimpleNamespace

from api.review.related import question_terms, related_papers, terms


def cell(paper_id, key, value, status="done", review=None):
    return SimpleNamespace(paper_id=paper_id, column_key=key, value_json=value, status=status,
                           review=review)  # fmt: skip


COLUMNS = {"problem_statement": "Problem", "key_findings": "Findings", "results": "Results"}


def test_terms_drop_stop_words_and_stem():
    assert terms("Does sleep duration affect students' grades?") == {
        "sleep", "duration", "student", "grade",
    }  # fmt: skip


def test_question_terms_include_parsed_constructs():
    parsed = {"constructs": [{"name": "academic performance"}], "population": "undergraduates"}
    got = question_terms("Does sleep matter?", parsed)
    assert {"sleep", "academic", "performance", "undergraduate"} <= got


def test_related_papers_rank_and_explain():
    rq = question_terms("Does short sleep lower grades in university students?", None)
    cells = [
        cell(1, "problem_statement", "Short sleep and grades of first-year university students"),
        cell(1, "key_findings", ["Less than six hours of sleep: lower grades"]),
        cell(2, "problem_statement", "Defect prediction across software projects"),
        cell(3, "results", "Students who sleep less had lower grades", review="rejected"),
        cell(3, "problem_statement", "Sleep apnoea in adults", status="not_found"),
    ]
    out = related_papers(rq, [(1, None), (2, "Graph networks"), (3, None)], cells, COLUMNS)
    assert [r.paper_id for r in out] == [1]
    assert {"sleep", "grade", "student", "university"} <= set(out[0].matched_terms)
    assert {c["column_key"] for c in out[0].cells} == {"problem_statement", "key_findings"}


def test_no_terms_no_matches():
    assert related_papers(set(), [(1, "x")], [], COLUMNS) == []
