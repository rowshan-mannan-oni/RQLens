"""Where project files live. Paths are built from IDs only, never from user input."""

import re
from pathlib import Path

from api.config import get_settings


def project_dir(project_id: int) -> Path:
    return get_settings().data_dir / "projects" / str(project_id)


def project_db_path(project_id: int) -> Path:
    return project_dir(project_id) / "data.duckdb"


def uploads_dir(project_id: int) -> Path:
    return project_dir(project_id) / "uploads"


def upload_path(project_id: int, dataset_id: int, filename: str = ".csv") -> Path:
    """The stored upload. Its extension follows the uploaded file's (`filename`), so the
    loader knows the format; CSV when unknown."""
    suffix = Path(filename).suffix.lower()
    if not suffix and filename.startswith("."):
        suffix = filename.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".csv"
    return uploads_dir(project_id) / f"{dataset_id}{suffix}"


def papers_dir(project_id: int) -> Path:
    return project_dir(project_id) / "papers"


def paper_path(project_id: int, paper_id: int) -> Path:
    return papers_dir(project_id) / f"{paper_id}.pdf"
