"""Download the dataset report as Markdown or PDF."""

import asyncio
import re
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response

from api.report.builder import gather, render_markdown
from api.report.pdf import to_pdf
from api.routes.deps import OwnedProject, Session

router = APIRouter(prefix="/projects/{project_id}/report", tags=["report"])


def _filename(title: str, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:60] or "project"
    return f"rq-lens-report-{slug}.{ext}"


@router.get("")
async def download_report(
    project: OwnedProject, session: Session, format: Literal["md", "pdf"] = "md"
) -> Response:
    text = render_markdown(await gather(session, project))
    if format == "pdf":
        pdf = await asyncio.to_thread(to_pdf, text, f"Dataset report: {project.title}")
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{_filename(project.title, "pdf")}"'
            },
        )
    return Response(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(project.title, "md")}"'},
    )
