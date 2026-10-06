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
    # When false, only aggregate statistics (no sample values) are sent to the LLM.
    share_samples: Mapped[bool] = mapped_column(default=True, server_default="true")


class ResearchQuestion(TimestampMixin, Base):
    __tablename__ = "research_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
    text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[Json | None]
    position: Mapped[int] = mapped_column(Integer, default=0)


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
    config_version: Mapped[str] = mapped_column(String(64))


class Insight(TimestampMixin, Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = fk("projects.id")
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
