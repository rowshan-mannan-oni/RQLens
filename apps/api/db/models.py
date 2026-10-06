"""App database schema. Mirrors section 5 of plan.md.

Uploaded data itself lives in a per-project DuckDB file, not here.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Json = Any


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {Json: JSONB}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def fk(target: str, *, nullable: bool = False, on_delete: str = "CASCADE") -> Any:
    return mapped_column(ForeignKey(target, ondelete=on_delete), index=True, nullable=nullable)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = fk("users.id")
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="new")
    duckdb_path: Mapped[str | None] = mapped_column(String(500))
    # Research questions the data could answer, suggested by the LLM.
    rq_suggestions_json: Mapped[Json | None]
    rq_suggestions_status: Mapped[str | None] = mapped_column(String(16))  # running|done|failed
    rq_suggestions_error: Mapped[str | None] = mapped_column(Text)
    # When false, only aggregate statistics (no sample values) are sent to the LLM.
    share_samples: Mapped[bool] = mapped_column(default=True, server_default="true")


class ProjectMember(TimestampMixin, Base):
    """Someone the owner shared the project with. Matched by email when they sign in."""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))  # viewer | editor
    user_id: Mapped[int | None] = fk("users.id", nullable=True, on_delete="SET NULL")
    invited_by: Mapped[int | None] = fk("users.id", nullable=True, on_delete="SET NULL")


class Comment(TimestampMixin, Base):
    """A comment on the project or on one of its items (a research question, a literature
    table cell, an insight, a dataset or a paper)."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    user_id: Mapped[int | None] = fk("users.id", nullable=True, on_delete="SET NULL")
    target_type: Mapped[str] = mapped_column(String(24))  # project | rq | cell | insight | ...
    target_id: Mapped[int | None] = mapped_column(Integer, index=True)
    body: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(default=False, server_default="false")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchQuestion(TimestampMixin, Base):
    __tablename__ = "research_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[Json | None]
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Column mapping (rq.schemas.Mapping). Kept across re-assessments; cleared when text changes.
    mapping_json: Mapped[Json | None]
    # queued | running | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    # Bumped on every edit, so a job started before the edit discards its result.
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Dataset(TimestampMixin, Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    table_name: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(500))
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    column_count: Mapped[int | None]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # queued | loading | profiling | ready | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    load_warnings_json: Mapped[Json | None]
    # upload: from a CSV file; combined: built from other datasets (spec in source_json)
    kind: Mapped[str] = mapped_column(String(16), default="upload", server_default="upload")
    source_json: Mapped[Json | None]
    # LLM column descriptions: pending | running | done | failed | skipped
    describe_status: Mapped[str | None] = mapped_column(String(16))
    describe_error: Mapped[str | None] = mapped_column(Text)


class DatasetColumn(Base):
    __tablename__ = "columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = fk("datasets.id")
    name: Mapped[str] = mapped_column(String(300))  # safe identifier used in SQL
    original_name: Mapped[str | None] = mapped_column(Text)  # header as written in the file
    physical_type: Mapped[str] = mapped_column(String(64))
    semantic_type: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    description_source: Mapped[str | None] = mapped_column(String(16))  # llm | user | dictionary
    description_confidence: Mapped[str | None] = mapped_column(String(8))  # high | medium | low
    is_pii: Mapped[bool] = mapped_column(default=False)
    pii_reason: Mapped[str | None] = mapped_column(String(200))
    profile_json: Mapped[Json | None]


class TableProfile(TimestampMixin, Base):
    __tablename__ = "table_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = fk("datasets.id")
    profile_json: Mapped[Json]
    warnings_json: Mapped[Json | None]


class TableRelationship(TimestampMixin, Base):
    """Candidate join key between two tables of a project, found by value overlap."""

    __tablename__ = "table_relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    left_dataset_id: Mapped[int] = fk("datasets.id")
    left_column: Mapped[str] = mapped_column(String(300))
    right_dataset_id: Mapped[int] = fk("datasets.id")
    right_column: Mapped[str] = mapped_column(String(300))
    shared_values: Mapped[int] = mapped_column(BigInteger)
    left_distinct: Mapped[int] = mapped_column(BigInteger)
    right_distinct: Mapped[int] = mapped_column(BigInteger)
    left_coverage: Mapped[float] = mapped_column(Float)
    right_coverage: Mapped[float] = mapped_column(Float)
    cardinality: Mapped[str] = mapped_column(String(16))
    name_match: Mapped[bool]


class RQAssessment(TimestampMixin, Base):
    __tablename__ = "rq_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    rq_id: Mapped[int] = fk("research_questions.id")
    verdict: Mapped[str] = mapped_column(String(16))  # answerable | partial | not_answerable
    mapped_columns_json: Mapped[Json | None]
    evidence_json: Mapped[Json | None]
    gaps_json: Mapped[Json | None]
    suggested_method: Mapped[str | None] = mapped_column(Text)
    threats_json: Mapped[Json | None]
    config_version: Mapped[str] = mapped_column(String(120))
    explanation: Mapped[str | None] = mapped_column(Text)
    rewording: Mapped[str | None] = mapped_column(Text)
    facts_json: Mapped[Json | None]  # neutral measurements shown as evidence
    grounding_json: Mapped[Json | None]
    explained_by: Mapped[str | None] = mapped_column(String(16))  # llm | rules
    problems_json: Mapped[Json | None]  # mapping fixes and failed checks


class InsightRun(TimestampMixin, Base):
    """One generation of a project's insights; the newest finished run is shown."""

    __tablename__ = "insight_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed
    error: Mapped[str | None] = mapped_column(Text)
    planned: Mapped[int | None]
    failed_json: Mapped[Json | None]  # analyses that could not run, with the reason
    dropped_json: Mapped[Json | None]  # planned analyses rejected by validation
    used_llm: Mapped[bool] = mapped_column(default=False, server_default="false")
    config_version: Mapped[str | None] = mapped_column(String(120))


class Insight(TimestampMixin, Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    run_id: Mapped[int | None] = fk("insight_runs.id", nullable=True)
    # finding | weak | no_evidence | data_quality
    status: Mapped[str | None] = mapped_column(String(16))
    spec_json: Mapped[Json | None]
    query_ids_json: Mapped[Json | None]
    grounding_json: Mapped[Json | None]
    written_by: Mapped[str | None] = mapped_column(String(16))  # template | llm
    rq_id: Mapped[int | None] = fk("research_questions.id", nullable=True, on_delete="SET NULL")
    title: Mapped[str] = mapped_column(String(300))
    statement: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    effect_size: Mapped[float | None] = mapped_column(Float)
    p_value: Mapped[float | None] = mapped_column(Float)
    p_adjusted: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)
    sql: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[Json | None]
    chart_json: Mapped[Json | None]
    caveats_json: Mapped[Json | None]


class Paper(TimestampMixin, Base):
    """An uploaded PDF. Its text is split into citable passages (`passages`)."""

    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    filename: Mapped[str] = mapped_column(String(500))
    folder: Mapped[str | None] = mapped_column(
        String(500)
    )  # subfolder path when uploaded as a folder
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # queued | parsing | ready | needs_ocr | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None]
    pages_json: Mapped[Json | None]  # [[width, height], ...] in PDF points
    passage_count: Mapped[int | None]
    char_count: Mapped[int | None]
    title: Mapped[str | None] = mapped_column(Text)
    authors_json: Mapped[Json | None]
    year: Mapped[int | None]
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300))
    metadata_source_json: Mapped[Json | None]  # field -> pdf_metadata | first_page | user
    sections_json: Mapped[Json | None]
    ocr_pages_json: Mapped[Json | None]  # pages whose text was read with OCR
    cite_key: Mapped[str | None] = mapped_column(String(200))  # from an imported reference file


class Passage(Base):
    """One citable unit of a paper, normally a sentence, with its position on the page."""

    __tablename__ = "passages"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = fk("papers.id")
    ordinal: Mapped[int]
    label: Mapped[str] = mapped_column(String(24))  # P3-S12: page 3, 12th passage on it
    page: Mapped[int]
    section: Mapped[str | None] = mapped_column(Text)
    section_kind: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # sentence | caption | reference
    text: Mapped[str] = mapped_column(Text)
    rects_json: Mapped[Json]  # [[x0, y0, x1, y1], ...], one per line, top-left origin


class ReferenceEntry(TimestampMixin, Base):
    """An entry of an imported BibTeX or RIS file. Matched to a paper by DOI or title, now or
    when its PDF is uploaded later."""

    __tablename__ = "reference_entries"
    __table_args__ = (UniqueConstraint("project_id", "cite_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    cite_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(Text)
    authors_json: Mapped[Json | None]
    year: Mapped[int | None]
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(300))
    files_json: Mapped[Json | None]  # PDF file names listed in the export
    paper_id: Mapped[int | None] = fk("papers.id", nullable=True, on_delete="SET NULL")


class ReviewTemplate(TimestampMixin, Base):
    """A user's own review template. Built-in templates live in code (review/templates.py)."""

    __tablename__ = "review_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = fk("users.id")
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    columns_json: Mapped[Json]
    version: Mapped[int] = mapped_column(default=1, server_default="1")


class ReviewTable(TimestampMixin, Base):
    """A project's literature table: one row per paper, one column per template field."""

    __tablename__ = "review_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    name: Mapped[str] = mapped_column(String(200))
    template_key: Mapped[str] = mapped_column(String(64))  # builtin:<name> or user:<id>
    # The columns as they were when the table was made; later template edits do not apply.
    columns_json: Mapped[Json]


class ReviewCell(Base):
    __tablename__ = "review_cells"
    __table_args__ = (UniqueConstraint("table_id", "paper_id", "column_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = fk("review_tables.id")
    paper_id: Mapped[int] = fk("papers.id")
    column_key: Mapped[str] = mapped_column(String(64))
    # queued | running | done | not_found | unverified | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued")
    value_json: Mapped[Json | None]
    source: Mapped[str | None] = mapped_column(String(16))  # llm | metadata | user
    # [{passage_id, label, page, quote, verified, score}], checked against the passage text
    citations_json: Mapped[Json | None]
    confidence: Mapped[str | None] = mapped_column(String(8))  # high | medium | low
    note: Mapped[str | None] = mapped_column(Text)  # not-found reason, check failure or error
    ai_json: Mapped[Json | None]  # the AI's last answer, kept when the user edits the cell
    review: Mapped[str | None] = mapped_column(String(16))  # accepted | rejected
    # Bumped on each re-run or edit, so a job started earlier discards its result.
    version: Mapped[int] = mapped_column(default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chat(TimestampMixin, Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    title: Mapped[str] = mapped_column(String(300))


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = fk("chats.id")
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    chart_json: Mapped[Json | None]
    # Assistant messages: kind, tool steps, query ids, grounding result, usage and limits hit.
    trace_json: Mapped[Json | None]


class Query(TimestampMixin, Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    message_id: Mapped[int | None] = fk("messages.id", nullable=True, on_delete="SET NULL")
    insight_id: Mapped[int | None] = fk("insights.id", nullable=True, on_delete="SET NULL")
    rq_assessment_id: Mapped[int | None] = fk(
        "rq_assessments.id", nullable=True, on_delete="SET NULL"
    )
    sql: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    result_preview_json: Mapped[Json | None]


class EvalRun(TimestampMixin, Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    suite: Mapped[str] = mapped_column(String(32))
    dataset_version: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[Json]
    git_sha: Mapped[str | None] = mapped_column(String(40))
    metrics_json: Mapped[Json | None]


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_run_id: Mapped[int] = fk("eval_runs.id")
    case_id: Mapped[str] = mapped_column(String(200))
    passed: Mapped[bool]
    details_json: Mapped[Json | None]
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))


class LLMCall(TimestampMixin, Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = fk("projects.id", nullable=True)
    eval_run_id: Mapped[int | None] = fk("eval_runs.id", nullable=True)
    step: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(default=0)
    request_json: Mapped[Json | None]
    response_json: Mapped[Json | None]
