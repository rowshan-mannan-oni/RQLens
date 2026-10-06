from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from api.db.models import Dataset, DatasetColumn, TableRelationship
from api.routes.deps import OwnedProject, Session

router = APIRouter(prefix="/projects/{project_id}/relationships", tags=["relationships"])


class Side(BaseModel):
    dataset_id: int
    filename: str
    table_name: str
    column: str
    column_label: str
    distinct: int
    coverage: float


class RelationshipOut(BaseModel):
    id: int
    left: Side
    right: Side
    shared_values: int
    cardinality: str
    name_match: bool


@router.get("")
async def list_relationships(project: OwnedProject, session: Session) -> list[RelationshipOut]:
    rows = (
        await session.scalars(
            select(TableRelationship)
            .where(TableRelationship.project_id == project.id)
            .order_by(TableRelationship.id)
        )
    ).all()
    if not rows:
        return []

    dataset_ids = {r.left_dataset_id for r in rows} | {r.right_dataset_id for r in rows}
    datasets = {
        d.id: d for d in await session.scalars(select(Dataset).where(Dataset.id.in_(dataset_ids)))
    }
    labels = {
        (c.dataset_id, c.name): c.original_name or c.name
        for c in await session.scalars(
            select(DatasetColumn).where(DatasetColumn.dataset_id.in_(dataset_ids))
        )
    }

    def side(dataset_id: int, column: str, distinct: int, coverage: float) -> Side:
        d = datasets[dataset_id]
        return Side(
            dataset_id=dataset_id,
            filename=d.original_filename,
            table_name=d.table_name,
            column=column,
            column_label=labels.get((dataset_id, column), column),
            distinct=distinct,
            coverage=coverage,
        )

    return [
        RelationshipOut(
            id=r.id,
            left=side(r.left_dataset_id, r.left_column, r.left_distinct, r.left_coverage),
            right=side(r.right_dataset_id, r.right_column, r.right_distinct, r.right_coverage),
            shared_values=r.shared_values,
            cardinality=r.cardinality,
            name_match=r.name_match,
        )
        for r in rows
    ]
