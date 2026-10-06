"""Background job: read an uploaded PDF into passages (run by the arq worker)."""

import asyncio
import logging
from functools import partial
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete, select

from api.config import get_settings
from api.db.models import Paper, Passage, ReferenceEntry
from api.db.session import get_sessionmaker
from api.papers import ocr
from api.papers.parser import ParsedPaper, parse_pdf
from api.papers.references import apply_to_paper, match
from api.storage import paper_path

log = logging.getLogger(__name__)


async def parse_paper(ctx: dict[str, Any], paper_id: int) -> str:
    async with get_sessionmaker()() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            return "missing"
        project_id = paper.project_id
        paper.status, paper.error = "parsing", None
        await session.commit()

    try:
        settings = get_settings()
        use_ocr = settings.ocr_enabled and ocr.available()
        parsed = await asyncio.to_thread(
            partial(parse_pdf, ocr=use_ocr, max_ocr_pages=settings.max_ocr_pages),
            paper_path(project_id, paper_id),
        )
    except Exception as exc:
        log.warning("parse_paper %s failed: %s", paper_id, exc)
        async with get_sessionmaker()() as session:
            paper = await session.get(Paper, paper_id)
            if paper is not None:
                paper.status = "failed"
                paper.error = f"Could not read the PDF: {exc}"[:2000]
                await session.commit()
        return "failed"

    async with get_sessionmaker()() as session:
        paper = await session.get(Paper, paper_id)
        if paper is None:
            return "missing"
        await session.execute(delete(Passage).where(Passage.paper_id == paper_id))
        session.add_all(_passages(paper_id, parsed))
        _store(paper, parsed)
        await _match_reference(session, paper)
        await session.commit()
        status = paper.status

    if status == "ready":
        await ctx["redis"].enqueue_job("extract_new_paper", paper_id)
    return status


def _passages(paper_id: int, parsed: ParsedPaper) -> list[Passage]:
    return [
        Passage(
            paper_id=paper_id,
            ordinal=p.ordinal,
            label=p.label,
            page=p.page,
            section=p.section or None,
            section_kind=p.section_kind,
            kind=p.kind,
            text=p.text,
            rects_json=[list(r) for r in p.rects],
        )
        for p in parsed.passages
    ]


def _store(paper: Paper, parsed: ParsedPaper) -> None:
    paper.page_count = parsed.page_count
    paper.pages_json = [list(s) for s in parsed.page_sizes]
    paper.char_count = parsed.char_count
    paper.passage_count = len(parsed.passages)
    paper.ocr_pages_json = parsed.ocr_pages or None
    paper.sections_json = [
        {"title": s.title, "kind": s.kind, "page": s.page, "first_ordinal": s.first_ordinal}
        for s in parsed.sections
    ]
    # Metadata the user corrected is kept.
    sources = {k: v for k, v in (paper.metadata_source_json or {}).items() if v == "user"}
    meta = parsed.metadata
    found: dict[str, Any] = {
        "title": meta.title,
        "authors": meta.authors or None,
        "year": meta.year,
        "venue": meta.venue,
        "doi": meta.doi,
    }
    for field, value in found.items():
        if field in sources:
            continue
        if field == "authors":
            paper.authors_json = value
        else:
            setattr(paper, field, value)
        if value is not None and field in meta.source:
            sources[field] = meta.source[field]
    paper.metadata_source_json = sources
    if parsed.needs_ocr:
        paper.status = "needs_ocr"
        paper.error = (
            "This PDF has no text layer (it looks scanned) and OCR is not available here, so "
            "its text cannot be cited. Run it through OCR and upload it again."
            if not ocr.available() or not get_settings().ocr_enabled
            else "This PDF has no readable text, even with OCR."
        )
    elif not parsed.passages:
        paper.status, paper.error = "failed", "No readable text was found in this PDF."
    else:
        paper.status, paper.error = "ready", None
        if parsed.ocr_pages:
            n = len(parsed.ocr_pages)
            paper.error = (
                f"{'All pages were' if n == parsed.page_count else f'{n} scanned page(s) were'} "
                "read with OCR. Check quotes against the page: OCR can misread characters."
            )


async def _match_reference(session: Any, paper: Paper) -> None:
    """Give a newly read paper the metadata of an imported reference entry that describes it."""
    entries = list(
        await session.scalars(
            select(ReferenceEntry).where(
                ReferenceEntry.project_id == paper.project_id,
                (ReferenceEntry.paper_id.is_(None)) | (ReferenceEntry.paper_id == paper.id),
            )
        )
    )
    for entry in entries:
        ref = SimpleNamespace(doi=entry.doi, title=entry.title)
        if match(ref, [paper]) is paper:
            entry.paper_id = paper.id
            apply_to_paper(paper, entry)
            return
