"""Build a project from the versioned development datasets without Postgres or Redis.

Loads each CSV with the real loader, profiles it and detects personal data, exactly as the
worker does, and returns a Catalog the chat agent can use.
"""

import json
from pathlib import Path
from typing import Any

from api.agent.catalog import Catalog, CatalogColumn, CatalogTable
from api.ingest.pipeline import run_load, run_pii, run_profile

DATASETS = Path(__file__).parent / "datasets"


def manifest() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads((DATASETS / "manifest.json").read_text())
    return entries


def build(db_path: Path, names: list[str] | None = None, topic: str | None = None) -> Catalog:
    """Load the named datasets (all by default) into db_path and return their catalog."""
    db_path.unlink(missing_ok=True)
    tables = []
    for entry in manifest():
        if names is not None and entry["name"] not in names:
            continue
        report = run_load(db_path, DATASETS / entry["file"], entry["name"])
        profile = run_profile(db_path, report)
        pii = run_pii(db_path, profile, report.table_name)
        tables.append(
            CatalogTable(
                name=report.table_name,
                filename=Path(entry["file"]).name,
                row_count=report.row_count,
                columns=[
                    CatalogColumn(
                        name=r.column.name,
                        label=r.column.original_name or r.column.name,
                        physical_type=r.column.physical_type,
                        semantic_type=r.profile["semantic_type"],
                        is_pii=pii[r.column.name].is_pii,
                        profile=r.profile,
                    )
                    for r in profile.columns
                ],
                warnings=[dict(w) for w in profile.warnings],
            )
        )
    return Catalog(project_id=0, topic=topic, share_samples=True, tables=tables)


def subset(catalog: Catalog, names: list[str]) -> Catalog:
    """The same catalog limited to some tables, as if the project held only those."""
    return Catalog(
        project_id=catalog.project_id,
        topic=catalog.topic,
        share_samples=catalog.share_samples,
        tables=[t for t in catalog.tables if t.name in names],
        joins=catalog.joins,
    )
