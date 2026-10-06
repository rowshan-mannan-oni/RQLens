from types import SimpleNamespace

import pytest

from api.papers.parser import parse_bytes
from api.review import extract as extract_mod
from api.review.citations import check_cell, normalise, quote_score
from api.review.extract import PaperInput, extract
from api.review.templates import BUILTIN, TemplateColumn
from evals.literature.synth import load_specs, render_pdf
from tests.test_rq import scripted_client

LIT = BUILTIN["builtin:literature_review"].columns


def as_rows(parsed):
    return [
        SimpleNamespace(
            id=p.ordinal + 1,
            ordinal=p.ordinal,
            label=p.label,
            page=p.page,
            text=p.text,
            kind=p.kind,
            section_kind=p.section_kind,
            section=p.section,
        )
        for p in parsed.passages
    ]


@pytest.fixture(scope="module")
def paper():
    parsed = parse_bytes(render_pdf(load_specs()["defect-gnn"]))
    m = parsed.metadata
    return PaperInput(as_rows(parsed), m.title, m.authors, m.year, m.venue, m.doi)


def label_of(paper, start: str) -> str:
    return next(p.label for p in paper.passages if p.text.startswith(start))


# --- citation check ----------------------------------------------------------------------------


def test_normalise_ignores_case_quotes_dashes_and_hyphenation():
    assert normalise("Cross\u2010project \u201cdefect\u201d  pre-\ndiction.") == normalise(
        'cross-project "defect" prediction'
    )
    assert normalise("crossproject") == normalise("cross-project")


def test_quote_score_exact_fuzzy_and_wrong():
    passage = "GraphDP achieves a mean F1 score of 0.64 and a mean AUC of 0.78 across projects."
    assert quote_score("achieves a mean F1 score of 0.64", passage) == 1.0
    assert quote_score("achieves a mean Fl score of 0.64 and a mean", passage) >= 0.9  # OCR-ish
    assert quote_score("reaches a mean F1 score of 0.91 on every project", passage) < 0.9
    assert quote_score("0.64", passage) == 1.0
    assert quote_score("0.65", passage) == 0.0  # short quotes must match exactly


def P(i: int, label: str, text: str):
    return SimpleNamespace(id=i, ordinal=i, label=label, page=1, text=text)


def test_check_cell_numbers_labels_and_adjacent_passages():
    passages = {
        "P1-S1": P(1, "P1-S1", "The mean F1 score is 0.64 on 18 projects."),
        "P1-S2": P(2, "P1-S2", "These patterns cor\u2010"),
        "P1-S3": P(3, "P1-S3", "respond to error-prone code."),
    }
    ok = check_cell("F1 = 0.64 on 18 projects", [("P1-S1", "mean F1 score is 0.64")], passages)
    assert ok.ok and ok.citations[0].verified

    bad_number = check_cell("F1 = 0.71", [("P1-S1", "mean F1 score is 0.64")], passages)
    assert not bad_number.ok and bad_number.unsupported_numbers == ["0.71"]

    unknown = check_cell("x", [("P9-S9", "anything")], passages)
    assert not unknown.ok and "P9-S9 is not a passage" in unknown.problems[0]

    spanning = check_cell(
        "patterns", [("P1-S2", "These patterns correspond to error-prone code"),
                     ("P1-S3", "respond to error-prone code")], passages,
    )  # fmt: skip
    assert spanning.ok

    assert not check_cell("x", [], passages).ok  # a found value needs a citation


# --- extraction ------------------------------------------------------------------------------


def answer(column, value, cites, confidence="high"):
    return {
        "column": column,
        "found": True,
        "value": value,
        "citations": [{"passage": p, "quote": q} for p, q in cites],
        "confidence": confidence,
        "reason": None,
    }


def not_found(column, reason):
    return {"column": column, "found": False, "value": None, "citations": [], "reason": reason}


async def test_extract_metadata_llm_check_and_retry(paper):
    res = label_of(paper, "GraphDP achieves a mean F1")
    lim = label_of(paper, "Our study only covers Java")
    data = label_of(paper, "We use 18 open-source Java")
    first = {
        "cells": [
            answer(
                "problem_statement",
                "Cross-project defect predictors built on metrics lose "
                "accuracy when projects differ.",
                [
                    (
                        label_of(paper, "The problem we address"),
                        "cross-project predictors built on traditional metrics",
                    )
                ],
            ),
            answer(
                "results",
                "Mean F1 of 0.66 and AUC of 0.78.",
                [(res, "GraphDP achieves a mean F1 score of 0.64")],
            ),  # wrong number
            answer(
                "datasets",
                ["PROMISE repository, 18 Java projects"],
                [(data, "We use 18 open-source Java projects from the PROMISE repository")],
            ),
            answer(
                "limitations",
                ["Only Java projects"],
                [(lim, "Our study only covers Java projects")],
            ),
            answer("metrics", ["F1 score", "AUC"], [("P7-S1", "invented passage")]),  # unknown ID
            not_found("future_work", "No future work is described."),
        ]
    }
    retry = {
        "cells": [
            answer(
                "results",
                "Mean F1 of 0.64 and AUC of 0.78.",
                [(res, "GraphDP achieves a mean F1 score of 0.64 and a mean AUC of 0.78")],
            ),
            answer("metrics", ["F1 score", "AUC"], [("P7-S1", "still invented")]),
        ]
    }
    client, requests = scripted_client([first, retry])
    out = await extract(client, LIT, paper)
    cells = {c.column_key: c for c in out.cells}

    # Metadata columns are filled without the AI and cited to the first page.
    assert cells["paper_title"].source == "metadata"
    assert cells["paper_title"].value == "Graph Neural Networks for Cross-Project Defect Prediction"
    assert cells["paper_title"].citations[0]["label"] == "P1-S1"
    assert cells["authors"].value == ["Maria Okafor", "Daniel Brandt", "Wei Zhang"]
    assert cells["year"].value == 2023.0

    first_request = requests[0]["messages"][1]["content"]
    assert '"key": "paper_title"' not in first_request  # not asked of the AI
    assert "[P1-S4] (abstract)" in first_request
    assert "Menzies" not in first_request  # references are never sent or cited

    assert cells["problem_statement"].status == "done"
    assert cells["results"].status == "done"  # fixed on retry
    assert cells["results"].citations[0]["verified"]
    assert cells["datasets"].value == ["PROMISE repository, 18 Java projects"]
    assert cells["limitations"].status == "done"
    assert cells["metrics"].status == "unverified"
    assert "P7-S1 is not a passage" in cells["metrics"].note
    assert cells["future_work"].status == "not_found"
    assert cells["future_work"].note == "No future work is described."
    # Columns the AI skipped fail visibly.
    assert cells["conclusion"].status == "failed"

    assert set(out.retried) == {"results", "metrics"}
    assert out.llm_calls == 2
    fix = requests[1]["messages"][-1]["content"]
    assert "0.66" in fix and "P7-S1" in fix


async def test_extract_without_ai_fills_metadata_only(paper):
    out = await extract(None, LIT, paper, no_ai_reason="Monthly AI limit reached.")
    cells = {c.column_key: c for c in out.cells}
    assert cells["paper_title"].status == "done"
    assert cells["approach"].status == "failed"
    assert cells["approach"].note == "Monthly AI limit reached."


async def test_category_and_number_columns(paper):
    columns = [
        TemplateColumn(
            label="Study type", kind="category", options=["Experiment", "Survey", "Case study"]
        ),
        TemplateColumn(label="Projects", kind="number"),
    ]
    first = {"cells": [
        answer("study_type", "experiment", [(label_of(paper, "We use 18"), "We use 18")]),
        answer("projects", "18 projects", [(label_of(paper, "We use 18"), "We use 18")]),
    ]}  # fmt: skip
    client, _ = scripted_client([first])
    out = await extract(client, columns, paper)
    study, projects = out.cells
    assert study.value == "Experiment" and study.status == "done"
    assert projects.value == 18.0 and projects.status == "done"


async def test_long_papers_send_selected_passages(paper, monkeypatch):
    monkeypatch.setattr(extract_mod, "LONG_PAPER_CHARS", 500)
    monkeypatch.setattr(extract_mod, "PASSAGES_PER_COLUMN", 3)
    client, requests = scripted_client([{"cells": []}])
    columns = [TemplateColumn(label="Limitations", instructions="Threats to validity")]
    out = await extract(client, columns, paper)
    sent = requests[0]["messages"][1]["content"]
    assert out.passages_sent < len([p for p in paper.passages if p.kind != "reference"])
    assert "Our study only covers Java" in sent  # most relevant to the column
    assert "(abstract)" in sent and "(conclusion)" in sent  # always sent
    assert "Early defect predictors" not in sent


async def test_check_can_be_switched_off(paper):
    first = {"cells": [answer("results", "F1 0.99", [(label_of(paper, "GraphDP achieves"), "x")])]}
    client, _ = scripted_client([first])
    out = await extract(client, [c for c in LIT if c.key == "results"], paper, check=False)
    assert out.cells[0].status == "done"
    assert out.llm_calls == 1
