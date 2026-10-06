"""Load what the AI may know about a project: tables, columns, profiles and joins."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.tools import ColumnInfo, ProjectContext, TableInfo
from api.db.models import Dataset, DatasetColumn, Project, TableProfile, TableRelationship


async def load_project_context(session: AsyncSession, project: Project) -> ProjectContext:
    datasets = (
        await session.scalars(
            select(Dataset)
            .where(Dataset.project_id == project.id, Dataset.status == "ready")
            .order_by(Dataset.id)
        )
    ).all()
    by_id = {d.id: d for d in datasets}
    columns: dict[int, list[ColumnInfo]] = {}
    if datasets:
        for c in await session.scalars(
            select(DatasetColumn)
            .where(DatasetColumn.dataset_id.in_(by_id))
            .order_by(DatasetColumn.id)
        ):
            columns.setdefault(c.dataset_id, []).append(
                ColumnInfo(
                    name=c.name,
                    label=c.original_name,
                    physical_type=c.physical_type,
                    semantic_type=c.semantic_type,
                    description=c.description,
                    description_source=c.description_source,
                    confidence=c.description_confidence,
                    is_pii=c.is_pii,
                    profile=c.profile_json,
                )
            )
    joins = [
        {
            "left": f"{by_id[r.left_dataset_id].table_name}.{r.left_column}",
            "right": f"{by_id[r.right_dataset_id].table_name}.{r.right_column}",
            "cardinality": r.cardinality,
        }
        for r in await session.scalars(
            select(TableRelationship).where(TableRelationship.project_id == project.id)
        )
        if r.left_dataset_id in by_id and r.right_dataset_id in by_id
    ]
    return ProjectContext(
        project_id=project.id,
        topic=project.topic,
        share_samples=project.share_samples,
        tables=[
            TableInfo(d.table_name, d.original_filename, d.row_count, columns.get(d.id, []))
            for d in datasets
        ],
        joins=joins,
    )


async def load_associations(
    session: AsyncSession, project_id: int
) -> dict[str, list[dict[str, Any]]]:
    """Pairwise associations from each ready table's profile, keyed by table name."""
    rows = await session.execute(
        select(Dataset.table_name, TableProfile.profile_json)
        .join(TableProfile, TableProfile.dataset_id == Dataset.id)
        .where(Dataset.project_id == project_id, Dataset.status == "ready")
        .order_by(TableProfile.id)
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for table, profile in rows:
        out[table] = list(((profile or {}).get("relationships") or {}).get("associations") or [])
    return out
