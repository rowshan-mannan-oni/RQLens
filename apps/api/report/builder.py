"""The dataset report: a draft of the "data" section of a paper, as Markdown or PDF.

Sections: overview, datasets, data dictionary, data-quality warnings, research-question fit,
top insights, and limitations, plus the newest literature table as an appendix. Every number
comes from the stored profile, assessments and insights (themselves computed by queries);
nothing is generated for the report itself.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import (
    Dataset,
    DatasetColumn,
    Insight,
    InsightRun,
    Paper,
    Project,
    ResearchQuestion,
    ReviewCell,
    ReviewTable,
    RQAssessment,
    TableProfile,
)

TOP_INSIGHTS = 10
DASH = "\u2013"  # shown for empty values
VERDICT_LABEL = {
    "answerable": "Answerable",
    "partial": "Partly answerable",
    "not_answerable": "Not answerable",
}
SOURCE_LABEL = {"user": "researcher", "dictionary": "data dictionary", "llm": "AI"}


@dataclass
class ColumnRow:
    name: str
    label: str
    type: str
    description: str | None
    description_source: str | None
    low_confidence: bool
    missing_pct: float
    distinct: int | None
    summary: str
    personal_data: bool


@dataclass
class DatasetSection:
    filename: str
    table: str
    rows: int
    columns: list[ColumnRow]
    warnings: list[dict[str, Any]]
    duplicate_rows: int | None
    missing_cells_pct: float | None
    combined: bool


@dataclass
class QuestionSection:
    text: str
    verdict: str | None
    explanation: str | None
    mapping: list[tuple[str, str, str, str]]  # concept, role, measured by, match
    checks: list[tuple[str, str]]  # level, message
    method: str | None
    threats: list[str]
    rewording: str | None


@dataclass
class LiteraturePaper:
    title: str
    byline: str  # authors and year
    fields: list[tuple[str, str, list[int], bool]]  # column, value, cited pages, unverified
    missing: list[str]  # columns the paper does not state


@dataclass
class LiteratureAppendix:
    name: str
    papers: list[LiteraturePaper]


@dataclass
class ReportData:
    title: str
    topic: str | None
    generated: dt.datetime
    datasets: list[DatasetSection]
    questions: list[QuestionSection]
    insights: list[dict[str, Any]]
    data_quality: list[str]
    insight_run: dict[str, Any] | None
    joins: int = 0
    notes: list[str] = field(default_factory=list)
    literature: LiteratureAppendix | None = None


def _summary(p: dict[str, Any]) -> str:
    """A one-line summary of a column's values from its profile."""
    num = p.get("numeric") or {}
    if num.get("finite"):
        return f"median {_n(num.get('median'))}, range {_n(num.get('min'))} to {_n(num.get('max'))}"
    dates = p.get("datetime") or {}
    if dates.get("min"):
        return f"{str(dates['min'])[:10]} to {str(dates['max'])[:10]}"
    top = p.get("top_values") or []
    if top:
        shown = ", ".join(f"{t['value']} ({100 * t['share']:.0f}%)" for t in top[:3])
        return f"most common: {shown}"
    return ""


def _n(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}" if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


async def gather(session: AsyncSession, project: Project) -> ReportData:
    datasets = list(
        await session.scalars(
            select(Dataset)
            .where(Dataset.project_id == project.id, Dataset.status == "ready")
            .order_by(Dataset.id)
        )
    )
    sections = []
    for d in datasets:
        cols = list(
            await session.scalars(
                select(DatasetColumn)
                .where(DatasetColumn.dataset_id == d.id)
                .order_by(DatasetColumn.id)
            )
        )
        profile = await session.scalar(
            select(TableProfile)
            .where(TableProfile.dataset_id == d.id)
            .order_by(TableProfile.id.desc())
            .limit(1)
        )
        table = (profile.profile_json if profile else None) or {}
        sections.append(
            DatasetSection(
                filename=d.original_filename,
                table=d.table_name,
                rows=d.row_count or 0,
                columns=[
                    ColumnRow(
                        name=c.name,
                        label=c.original_name or c.name,
                        type=c.semantic_type or c.physical_type,
                        description=c.description,
                        description_source=c.description_source,
                        low_confidence=c.description_source == "llm"
                        and c.description_confidence == "low",
                        missing_pct=float((c.profile_json or {}).get("missing_pct") or 0),
                        distinct=(c.profile_json or {}).get("distinct"),
                        summary="" if c.is_pii else _summary(c.profile_json or {}),
                        personal_data=c.is_pii,
                    )
                    for c in cols
                ],
                warnings=list((profile.warnings_json if profile else None) or []),
                duplicate_rows=table.get("duplicate_rows"),
                missing_cells_pct=table.get("missing_cells_pct"),
                combined=d.kind == "combined",
            )
        )

    questions = []
    for rq in await session.scalars(
        select(ResearchQuestion)
        .where(ResearchQuestion.project_id == project.id)
        .order_by(ResearchQuestion.position, ResearchQuestion.id)
    ):
        a = await session.scalar(
            select(RQAssessment)
            .where(RQAssessment.rq_id == rq.id)
            .order_by(RQAssessment.id.desc())
            .limit(1)
        )
        mapping = []
        for c in ((a.mapped_columns_json if a else None) or rq.mapping_json or {}).get(
            "constructs", []
        ):
            cand = None if c.get("status") == "rejected" else (c.get("candidates") or [None])[0]
            measured = (
                (cand.get("expression") or f"{cand.get('table')}.{cand.get('column')}")
                if cand
                else "no column (gap)"
            )
            mapping.append(
                (
                    c.get("name", ""),
                    c.get("role", ""),
                    measured,
                    cand.get("match", "") if cand else "",
                )
            )
        questions.append(
            QuestionSection(
                text=rq.text,
                verdict=a.verdict if a else None,
                explanation=a.explanation if a else None,
                mapping=mapping,
                checks=[
                    (r.get("level", ""), r.get("message", ""))
                    for r in ((a.evidence_json if a else None) or [])
                    if r.get("level") in ("fail", "warn", "info")
                ],
                method=a.suggested_method if a else None,
                threats=list((a.threats_json if a else None) or []),
                rewording=a.rewording if a else None,
            )
        )

    run = await session.scalar(
        select(InsightRun)
        .where(InsightRun.project_id == project.id, InsightRun.status == "done")
        .order_by(InsightRun.id.desc())
        .limit(1)
    )
    insights: list[dict[str, Any]] = []
    data_quality: list[str] = []
    if run is not None:
        for i in await session.scalars(
            select(Insight)
            .where(Insight.run_id == run.id)
            .order_by(Insight.score.desc().nulls_last(), Insight.id)
        ):
            if i.kind == "data_quality":
                data_quality.append(i.statement)
            elif i.status == "finding" and len(insights) < TOP_INSIGHTS:
                insights.append(
                    {
                        "title": i.title,
                        "statement": i.statement,
                        "caveats": [
                            c for c in (i.caveats_json or []) if not c.startswith("Exploratory")
                        ],
                    }
                )
    return ReportData(
        title=project.title,
        topic=project.topic,
        generated=dt.datetime.now(dt.UTC),
        datasets=sections,
        questions=questions,
        insights=insights,
        data_quality=data_quality,
        insight_run={"planned": run.planned, "created_at": run.created_at} if run else None,
        literature=await _literature(session, project.id),
    )


def _value_text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


async def _literature(session: AsyncSession, project_id: int) -> LiteratureAppendix | None:
    """The newest literature table, one entry per paper. Metadata columns (title, authors,
    year) form the heading; rejected values are left out."""
    table = await session.scalar(
        select(ReviewTable)
        .where(ReviewTable.project_id == project_id)
        .order_by(ReviewTable.id.desc())
        .limit(1)
    )
    if table is None:
        return None
    columns = [
        c for c in table.columns_json if c.get("metadata") not in ("title", "authors", "year")
    ]
    cells = {
        (c.paper_id, c.column_key): c
        for c in await session.scalars(select(ReviewCell).where(ReviewCell.table_id == table.id))
    }
    papers = []
    for p in await session.scalars(
        select(Paper)
        .where(Paper.project_id == project_id, Paper.status == "ready")
        .order_by(Paper.year.nulls_last(), Paper.title, Paper.filename)
    ):
        authors = list(p.authors_json or [])
        who = (authors[0] + (" et al." if len(authors) > 2 else f" and {authors[1]}"
               if len(authors) == 2 else "")) if authors else ""  # fmt: skip
        byline = ", ".join(x for x in (who, str(p.year) if p.year else "") if x)
        fields, missing = [], []
        for col in columns:
            cell = cells.get((p.id, col["key"]))
            if cell is None or cell.review == "rejected":
                continue
            if cell.status == "not_found":
                missing.append(col["label"])
                continue
            if cell.status not in ("done", "unverified"):
                continue
            text = _value_text(cell.value_json)
            if not text:
                continue
            pages = sorted({c["page"] for c in (cell.citations_json or []) if c.get("page")})
            fields.append((col["label"], text, pages, cell.status == "unverified"))
        papers.append(LiteraturePaper(p.title or p.filename, byline, fields, missing))
    return LiteratureAppendix(table.name, papers) if papers else None


# ---- Markdown ---------------------------------------------------------------------------


def _cell(text: Any) -> str:
    """Make text safe inside a Markdown table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _pct(x: float | None) -> str:
    return DASH if x is None else f"{100 * x:.1f}%"


def render_markdown(r: ReportData) -> str:
    out: list[str] = [f"# Dataset report: {r.title}", ""]
    out.append(
        f"Generated by RQ Lens on {r.generated:%d %B %Y}. Every figure comes from a query over "
        "the uploaded data. Use this as a draft for the data section of a paper, and check it "
        "against the data before publishing."
    )
    out.append("")
    if r.topic:
        out += ["**Research topic.** " + r.topic.strip(), ""]

    # Overview
    out += ["## 1. Overview", ""]
    if not r.datasets:
        out += ["No datasets have been profiled yet.", ""]
    else:
        total_rows = sum(d.rows for d in r.datasets)
        total_cols = sum(len(d.columns) for d in r.datasets)
        out.append(
            f"The project holds {len(r.datasets)} table{'s' if len(r.datasets) != 1 else ''} "
            f"with {total_rows:,} rows and {total_cols:,} columns in total."
        )
        out += ["", "| File | Table | Rows | Columns | Missing cells | Duplicate rows |"]
        out.append("|---|---|---:|---:|---:|---:|")
        for d in r.datasets:
            out.append(
                f"| {_cell(d.filename)}{' (combined)' if d.combined else ''} | `{d.table}` | "
                f"{d.rows:,} | {len(d.columns):,} | {_pct(d.missing_cells_pct)} | "
                f"{DASH if d.duplicate_rows is None else f'{d.duplicate_rows:,}'} |"
            )
        out.append("")

    # Data dictionary
    out += ["## 2. Data dictionary", ""]
    for d in r.datasets:
        out += [f"### {_cell(d.filename)} (`{d.table}`)", ""]
        out.append("| Column | Type | Description | Missing | Distinct | Values |")
        out.append("|---|---|---|---:|---:|---|")
        for c in d.columns:
            desc = c.description or DASH
            if c.description and c.description_source:
                desc += f" *({SOURCE_LABEL.get(c.description_source, c.description_source)}"
                desc += ", low confidence)*" if c.low_confidence else ")*"
            label = c.label if c.label == c.name else f"{c.label} (`{c.name}`)"
            values = "personal data, not shown" if c.personal_data else c.summary
            out.append(
                f"| {_cell(label)} | {_cell(c.type)} | {_cell(desc)} | {_pct(c.missing_pct)} | "
                f"{DASH if c.distinct is None else f'{c.distinct:,}'} | {_cell(values)} |"
            )
        out.append("")

    # Quality
    out += ["## 3. Data quality", ""]
    any_warning = False
    for d in r.datasets:
        ws = [w for w in d.warnings if w.get("severity") in ("severe", "warning")]
        if not ws:
            continue
        any_warning = True
        out += [f"**{_cell(d.filename)}**", ""]
        order = {"severe": 0, "warning": 1}
        for w in sorted(ws, key=lambda w: order.get(w.get("severity", ""), 2)):
            out.append(f"- {'**Severe:** ' if w.get('severity') == 'severe' else ''}{w['message']}")
        out.append("")
    if not any_warning:
        out += ["The profiler raised no data-quality warnings.", ""]

    # RQ fit
    out += ["## 4. Research-question fit", ""]
    if not r.questions:
        out += ["No research questions have been added.", ""]
    for i, q in enumerate(r.questions, 1):
        out += [f"### RQ{i}. {q.text}", ""]
        if q.verdict is None:
            out += ["Not assessed yet.", ""]
            continue
        out += [
            f"**Verdict: {VERDICT_LABEL.get(q.verdict, q.verdict)}.** {q.explanation or ''}",
            "",
        ]
        if q.mapping:
            out += ["| Concept | Role | Measured by | Match |", "|---|---|---|---|"]
            out += [
                f"| {_cell(c)} | {_cell(role)} | `{_cell(m)}` | {_cell(match) or DASH} |"
                for c, role, m, match in q.mapping
            ]
            out.append("")
        if q.checks:
            level_label = {"fail": "Blocks", "warn": "Limits", "info": "Note"}
            out += [f"- *{level_label.get(lvl, lvl)}:* {msg}" for lvl, msg in q.checks]
            out.append("")
        if q.method:
            out += [f"**Suggested method.** {q.method}", ""]
        if q.threats:
            out += ["**Threats to validity.**", "", *[f"- {t}" for t in q.threats], ""]
        if q.rewording:
            out += [f"**A version the data can answer.** {q.rewording}", ""]

    # Insights
    out += ["## 5. Exploratory insights", ""]
    if r.insight_run is None:
        out += ["Insights have not been generated.", ""]
    else:
        out.append(
            f"{r.insight_run['planned']} analyses were run with fixed statistical tests; "
            "p-values were adjusted for multiple testing (Benjamini-Hochberg) and results ranked "
            "by relevance, effect size and sample size. These are hypotheses to test, not "
            "confirmed results."
        )
        out.append("")
        if r.data_quality:
            out += ["**Data quality affecting the research questions.**", ""]
            out += [f"- {s}" for s in r.data_quality]
            out.append("")
        if r.insights:
            for k, ins in enumerate(r.insights, 1):
                out.append(f"{k}. **{ins['title']}.** {ins['statement']}")
                for c in ins["caveats"]:
                    out.append(f"   - {c}")
            out.append("")
        else:
            out += ["No finding passed the correction for multiple testing.", ""]

    # Limitations
    out += ["## 6. Limitations of this report", ""]
    out += [
        "- Descriptions marked *AI* were written by a language model from column names and "
        "statistics; check them against the data documentation.",
        "- Associations in the profile are computed on a sample of up to 50,000 rows on large "
        "tables.",
        "- Research-question verdicts come from fixed rules over measured checks. They are "
        "guidance for planning, not a substitute for a statistical analysis plan.",
        "- Observational data supports statements about association, not cause.",
        "- Codes such as -999 are flagged by the profiler but not removed; analyses include them "
        "unless stated.",
        "",
    ]
    if r.literature:
        out += _render_literature(r.literature)
    return "\n".join(out)


def _render_literature(lit: LiteratureAppendix) -> list[str]:
    out = [f"## Appendix A. Literature: {_cell(lit.name)}", ""]
    out += [
        "Values were extracted from each paper by AI and cite the sentences they came from; "
        "page numbers refer to the paper's PDF. Citations were checked against the paper "
        "text, and values marked *unverified* failed that check. Values you edited appear as "
        "you wrote them.",
        "",
    ]
    for p in lit.papers:
        out += [f"### {_cell(p.title)}" + (f" ({_cell(p.byline)})" if p.byline else ""), ""]
        for label, text, pages, unverified in p.fields:
            where = f" (p. {', '.join(str(n) for n in pages)})" if pages else ""
            flag = " *unverified*" if unverified else ""
            out.append(f"- **{_cell(label)}:** {_cell(text)}{where}{flag}")
        if p.missing:
            out.append(f"- *Not stated:* {', '.join(_cell(m) for m in p.missing)}")
        out.append("")
    return out
