"""Build synthetic research papers as PDFs, so tests and benchmark D know every sentence.

A paper is described by a `PaperSpec`: metadata, a layout (one or two columns), sections with
paragraphs, table captions and references. `render_pdf` lays it out with WeasyPrint the way
real papers look: a full-width title block, running headers, page numbers, automatic
hyphenation in narrow columns. `scanned_pdf` turns a PDF into page images with no text layer.
"""

import html
from dataclasses import dataclass, field

import pymupdf


@dataclass
class SectionSpec:
    heading: str
    paragraphs: list[str]
    tables: list[str] = field(default_factory=list)  # captions, placed after the paragraphs


@dataclass
class PaperSpec:
    title: str
    authors: list[str]
    affiliations: list[str]
    year: int
    abstract: str
    sections: list[SectionSpec]
    references: list[str] = field(default_factory=list)
    venue: str | None = None
    doi: str | None = None
    layout: str = "two"  # one | two
    running_header: str | None = None
    abstract_style: str = "heading"  # heading ("Abstract" on its own line) | inline ("Abstract—")


CSS = """
@page { size: A4; margin: 22mm 18mm 22mm;
  @top-center { content: string(header); font-size: 8pt; color: #555; }
  @bottom-center { content: counter(page); font-size: 8pt; } }
body { font-family: "DejaVu Serif", serif; font-size: 9.5pt; line-height: 1.3; text-align: justify;
       hyphens: auto; }
.header { string-set: header content(); display: none; }
h1 { font-size: 17pt; text-align: center; margin: 0 0 8pt; hyphens: manual; }
.authors { text-align: center; font-size: 10.5pt; margin: 0; }
.aff { text-align: center; font-size: 8.5pt; color: #333; margin: 2pt 0 0; }
.venue { text-align: center; font-size: 8pt; margin: 4pt 0 10pt; color: #333; }
.cols { columns: 2; column-gap: 7mm; }
h2 { font-size: 11pt; margin: 9pt 0 4pt; font-weight: bold; text-align: left; hyphens: manual; }
p { margin: 0 0 5pt; }
.caption { font-size: 8.5pt; margin: 6pt 0; }
.ref { font-size: 8pt; margin: 0 0 3pt; text-align: left; }
.abs-inline b { font-style: italic; }
"""


def to_html(spec: PaperSpec) -> str:
    e = html.escape
    head = []
    if spec.running_header:
        head.append(f'<div class="header">{e(spec.running_header)}</div>')
    head.append(f"<h1>{e(spec.title)}</h1>")
    head.append(f'<p class="authors">{e(", ".join(spec.authors))}</p>')
    head += [f'<p class="aff">{e(a)}</p>' for a in spec.affiliations]
    venue = spec.venue or ""
    if spec.doi:
        venue += f"{' \u00b7 ' if venue else ''}DOI: {spec.doi}"
    venue += f"{' \u00b7 ' if venue else ''}\u00a9 {spec.year}"
    head.append(f'<p class="venue">{e(venue)}</p>')

    body = []
    if spec.abstract_style == "inline":
        body.append(f'<p class="abs-inline"><b>Abstract\u2014</b>{e(spec.abstract)}</p>')
    else:
        body.append(f"<h2>Abstract</h2><p>{e(spec.abstract)}</p>")
    for s in spec.sections:
        body.append(f"<h2>{e(s.heading)}</h2>")
        body += [f"<p>{e(p)}</p>" for p in s.paragraphs]
        body += [f'<p class="caption">{e(c)}</p>' for c in s.tables]
    if spec.references:
        body.append(f"<h2>{len(spec.sections) + 1}. References</h2>")
        body += [f'<p class="ref">[{i}] {e(r)}</p>' for i, r in enumerate(spec.references, 1)]
    wrap = "cols" if spec.layout == "two" else "single"
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><style>{CSS}</style></head>"
        f"<body>{''.join(head)}<div class='{wrap}'>{''.join(body)}</div></body></html>"
    )


def render_pdf(spec: PaperSpec) -> bytes:
    from weasyprint import HTML

    pdf: bytes = HTML(string=to_html(spec)).write_pdf()
    return pdf


def scanned_pdf(pdf: bytes, dpi: int = 100) -> bytes:
    """The same pages as images only, like a scanned paper."""
    src = pymupdf.open(stream=pdf, filetype="pdf")
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    data: bytes = out.tobytes()
    return data


def load_specs(path: str | None = None) -> dict[str, PaperSpec]:
    """The synthetic corpus in papers.v1.json, by paper id."""
    import json
    from pathlib import Path

    file = Path(path) if path else Path(__file__).with_name("papers.v1.json")
    out: dict[str, PaperSpec] = {}
    for raw in json.loads(file.read_text()):
        raw = dict(raw)
        pid = raw.pop("id")
        raw["sections"] = [SectionSpec(**s) for s in raw["sections"]]
        out[pid] = PaperSpec(**raw)
    return out
