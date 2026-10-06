"""Dataset report: Markdown content and PDF rendering."""

import datetime as dt

from api.report.builder import (
    ColumnRow,
    DatasetSection,
    QuestionSection,
    ReportData,
    _summary,
    render_markdown,
)
from api.report.pdf import to_html, to_pdf


def sample() -> ReportData:
    return ReportData(
        title="Wage gaps",
        topic="Union membership and wages",
        generated=dt.datetime(2026, 10, 6, tzinfo=dt.UTC),
        datasets=[
            DatasetSection(
                filename="cps.csv",
                table="cps",
                rows=534,
                columns=[
                    ColumnRow("wage", "Wage ($/h)", "numeric", "Hourly wage | in dollars", "llm",
                              True, 0.0, 238, "median 7.78, range 1 to 44.5", False),
                    ColumnRow("email", "email", "identifier", None, None, False, 0.0, 534,
                              "a@b.com", True),
                ],
                warnings=[
                    {"severity": "warning", "message": "'wage' has 3 outliers."},
                    {"severity": "info", "message": "not shown"},
                    {"severity": "severe", "message": "'x' is missing in 80% of rows."},
                ],
                duplicate_rows=0,
                missing_cells_pct=0.012,
                combined=False,
            )
        ],
        questions=[
            QuestionSection(
                text="Do union members earn more?",
                verdict="partial",
                explanation="Partly answerable: 96 union members.",
                mapping=[("wage", "dependent", "cps.wage", "direct"),
                         ("tenure", "covariate", "no column (gap)", "")],
                checks=[("warn", "No column measures the covariate “tenure”.")],
                method="Mann-Whitney U.",
                threats=["Self-selection into unions."],
                rewording="Is union membership associated with wages?",
            ),
            QuestionSection("Unassessed?", None, None, [], [], None, [], None),
        ],
        insights=[{"title": "wage by union", "statement": "Wages differ (n = 534).",
                   "caveats": ["Only rows where x."]}],
        data_quality=["“wage” is missing in 2% of rows."],
        insight_run={"planned": 12},
    )  # fmt: skip


def test_markdown_has_every_section_in_order() -> None:
    md = render_markdown(sample())
    headings = [line for line in md.splitlines() if line.startswith("## ")]
    assert headings == [
        "## 1. Overview",
        "## 2. Data dictionary",
        "## 3. Data quality",
        "## 4. Research-question fit",
        "## 5. Exploratory insights",
        "## 6. Limitations of this report",
    ]
    assert "534 rows" in md and "1.2%" in md


def test_tables_are_escaped_and_personal_data_hidden() -> None:
    md = render_markdown(sample())
    assert "Hourly wage \\| in dollars *(AI, low confidence)*" in md
    assert "Wage ($/h) (`wage`)" in md
    assert "a@b.com" not in md and "personal data, not shown" in md


def test_quality_lists_severe_first_and_skips_info() -> None:
    md = render_markdown(sample())
    quality = md.split("## 3. Data quality")[1].split("## 4.")[0]
    assert quality.index("**Severe:**") < quality.index("3 outliers")
    assert "not shown" not in quality


def test_rq_section() -> None:
    md = render_markdown(sample())
    assert "**Verdict: Partly answerable.** Partly answerable: 96 union members." in md
    assert "| tenure | covariate | `no column (gap)` | \u2013 |" in md
    assert "*Limits:* No column measures" in md
    assert "Not assessed yet." in md
    assert "12 analyses were run" in md and "1. **wage by union.**" in md


def test_empty_project() -> None:
    r = sample()
    r.datasets, r.questions, r.insight_run = [], [], None
    md = render_markdown(r)
    assert "No datasets have been profiled yet." in md
    assert "Insights have not been generated." in md


def test_column_summaries() -> None:
    assert _summary({"numeric": {"finite": 3, "median": 2.5, "min": 1, "max": 1234567}}) == (
        "median 2.5, range 1 to 1,234,567"
    )
    assert _summary({"top_values": [{"value": "a", "share": 0.5}]}) == "most common: a (50%)"
    assert _summary({"datetime": {"min": "2020-01-01T00:00", "max": "2021-01-01"}}) == (
        "2020-01-01 to 2021-01-01"
    )


def test_pdf_renders() -> None:
    md = render_markdown(sample())
    assert "<table>" in to_html(md, "t") and "<title>t</title>" in to_html(md, "t")
    pdf = to_pdf(md, "Dataset report")
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000
