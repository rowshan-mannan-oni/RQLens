"""Build a project from the versioned development datasets without Postgres or Redis.

Loads each CSV with the real loader, profiles it and detects personal data, exactly as the
worker does, and returns the ProjectContext the chat agent uses.
"""

import json
from pathlib import Path
from typing import Any

from api.agent.tools import ColumnInfo, ProjectContext, TableInfo
from api.ingest.pipeline import run_load, run_pii, run_profile

DATASETS = Path(__file__).parent / "datasets"


def manifest() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = json.loads((DATASETS / "manifest.json").read_text())
    return entries


def build(db_path: Path, names: list[str] | None = None) -> ProjectContext:
    """Load the named datasets (all by default) into db_path and return their context."""
    return build_with_associations(db_path, names)[0]


def build_with_associations(
    db_path: Path, names: list[str] | None = None
) -> tuple[ProjectContext, dict[str, list[dict[str, Any]]]]:
    """Like build, plus each table's pairwise associations from the profile."""
    db_path.unlink(missing_ok=True)
    tables = []
    associations: dict[str, list[dict[str, Any]]] = {}
    for entry in manifest():
        if names is not None and entry["name"] not in names:
            continue
        report = run_load(db_path, DATASETS / entry["file"], entry["name"])
        profile = run_profile(db_path, report)
        pii = run_pii(db_path, profile, report.table_name)
        associations[report.table_name] = list(
            (profile.table.get("relationships") or {}).get("associations") or []
        )
        tables.append(
            TableInfo(
                table=report.table_name,
                filename=Path(entry["file"]).name,
                rows=report.row_count,
                columns=[
                    ColumnInfo(
                        name=r.column.name,
                        label=r.column.original_name,
                        physical_type=r.column.physical_type,
                        semantic_type=r.profile["semantic_type"],
                        description=None,
                        description_source=None,
                        confidence=None,
                        is_pii=pii[r.column.name].is_pii,
                        profile=r.profile,
                    )
                    for r in profile.columns
                ],
            )
        )
    ctx = ProjectContext(project_id=0, topic=None, share_samples=True, tables=tables)
    return ctx, associations


def subset(ctx: ProjectContext, names: list[str]) -> ProjectContext:
    """The same context limited to some tables, as if the project held only those."""
    return ProjectContext(
        project_id=ctx.project_id,
        topic=ctx.topic,
        share_samples=ctx.share_samples,
        tables=[t for t in ctx.tables if t.table in names],
        joins=ctx.joins,
    )
