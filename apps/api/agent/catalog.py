"""A read-only snapshot of a project's tables and columns for the chat agent.

Loaded from Postgres once per question, so tools can answer schema questions without a database
round trip, and tests can build one by hand.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import Dataset, DatasetColumn, Project, TableProfile, TableRelationship


@dataclass
class CatalogColumn:
    name: str
    label: str  # header as written in the file
    physical_type: str
    semantic_type: str | None
    description: str | None = None
    description_source: str | None = None
    confidence: str | None = None
    is_pii: bool = False
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class CatalogTable:
    name: str
    filename: str
    row_count: int
    columns: list[CatalogColumn]
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def column(self, name: str) -> CatalogColumn | None:
        lowered = name.lower()
        return next((c for c in self.columns if c.name.lower() == lowered), None)


@dataclass
class Catalog:
    project_id: int
    topic: str | None
    share_samples: bool
    tables: list[CatalogTable]
    joins: list[dict[str, Any]] = field(default_factory=list)

    def table(self, name: str) -> CatalogTable | None:
        lowered = name.lower()
        return next((t for t in self.tables if t.name.lower() == lowered), None)

    @property
    def column_count(self) -> int:
        return sum(len(t.columns) for t in self.tables)

    @property
    def pii_columns(self) -> set[str]:
        return {c.name.lower() for t in self.tables for c in t.columns if c.is_pii}


async def load_catalog(session: AsyncSession, project: Project) -> Catalog:
    datasets = list(
        await session.scalars(
            select(Dataset)
            .where(Dataset.project_id == project.id, Dataset.status == "ready")
            .order_by(Dataset.id)
        )
    )
    ids = [d.id for d in datasets]
    columns: dict[int, list[DatasetColumn]] = {i: [] for i in ids}
    for col in await session.scalars(
        select(DatasetColumn).where(DatasetColumn.dataset_id.in_(ids)).order_by(DatasetColumn.id)
    ):
        columns[col.dataset_id].append(col)
    warnings: dict[int, list[dict[str, Any]]] = {}
    for profile in await session.scalars(
        select(TableProfile).where(TableProfile.dataset_id.in_(ids)).order_by(TableProfile.id)
    ):
        warnings[profile.dataset_id] = list(profile.warnings_json or [])

    by_id = {d.id: d for d in datasets}
    joins = []
    for r in await session.scalars(
        select(TableRelationship).where(TableRelationship.project_id == project.id)
    ):
        left, right = by_id.get(r.left_dataset_id), by_id.get(r.right_dataset_id)
        if left and right:
            joins.append(
                {
                    "left": f"{left.table_name}.{r.left_column}",
                    "right": f"{right.table_name}.{r.right_column}",
                    "cardinality": r.cardinality,
                    "left_coverage": round(r.left_coverage, 3),
                    "right_coverage": round(r.right_coverage, 3),
                }
            )

    return Catalog(
        project_id=project.id,
        topic=project.topic,
        share_samples=project.share_samples,
        tables=[
            CatalogTable(
                name=d.table_name,
                filename=d.original_filename,
                row_count=d.row_count or 0,
                columns=[
                    CatalogColumn(
                        name=c.name,
                        label=c.original_name or c.name,
                        physical_type=c.physical_type,
                        semantic_type=c.semantic_type,
                        description=c.description,
                        description_source=c.description_source,
                        confidence=c.description_confidence,
                        is_pii=c.is_pii,
                        profile=c.profile_json or {},
                    )
                    for c in columns[d.id]
                ],
                warnings=warnings.get(d.id, []),
            )
            for d in datasets
        ],
        joins=joins,
    )
