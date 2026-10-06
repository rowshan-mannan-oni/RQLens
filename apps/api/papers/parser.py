"""Parse a PDF paper into citable passages with their positions on the page.

Text is read with PyMuPDF character by character, so every passage keeps one rectangle per line
it covers; the reader highlights exactly those rectangles. Steps, per page:

1. Drop running headers, footers, page numbers and rotated margin stamps (text that repeats in
   the top or bottom margin of most pages).
2. Order blocks for reading: on two-column pages, the left column before the right one, with
   full-width blocks (title, wide figures) splitting the page into bands.
3. Detect section headings from common heading words, numbering and font size.
4. Join each block's lines (undoing hyphenated line breaks) and split it into sentences.
   Captions ("Table 2: ...") are one passage; each reference entry is one passage.

Passages never cross a page. They are labelled `P<page>-S<n>` (the n-th passage on that page).
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import pymupdf

Rect = tuple[float, float, float, float]
# One character of a block's text: the character, its rectangle (None for inserted spaces) and
# the index of its line (numbered across a page's blocks).
Char = tuple[str, Rect | None, int]

# Fewer extractable characters per page than this means a scanned PDF without a text layer.
MIN_CHARS_PER_PAGE = 40
MARGIN_SHARE = 0.09  # top and bottom share of the page searched for running headers/footers
MAX_PASSAGE_CHARS = 700

SECTION_WORDS: list[tuple[str, str]] = [
    ("abstract", r"abstract|summary"),
    ("keywords", r"keywords|index terms"),
    ("introduction", r"introduction|motivation"),
    ("background", r"background|preliminaries"),
    ("related_work", r"related work|related works|literature review|prior work|state of the art"),
    (
        "method",
        r"methods?|methodology|approach|proposed (?:method|approach)|study design|materials and "
        r"methods|research method(?:ology)?",
    ),
    ("experiments", r"experiments?|experimental setup|evaluation|experimental evaluation|setup"),
    ("results", r"results?|findings|results and discussion"),
    ("discussion", r"discussion"),
    ("limitations", r"limitations?|threats to validity|validity threats"),
    ("conclusion", r"conclusions?|concluding remarks|conclusion and future work"),
    ("future_work", r"future work|future directions"),
    ("acknowledgements", r"acknowledge?ments?"),
    ("references", r"references|bibliography|works cited"),
    ("appendix", r"appendix|appendices|supplementary material"),
]
NUMBERING = r"(?:(?:\d+(?:\.\d+)*|[IVXL]+|[A-Z])[.)]?\s+)?"
HEADING_RE = [
    (kind, re.compile(rf"^{NUMBERING}(?:{words})\s*[:.]?$", re.IGNORECASE))
    for kind, words in SECTION_WORDS
]
# "Abstract—We present ..." or "Abstract: ..." starts a section inside a paragraph.
INLINE_HEADING_RE = re.compile(
    r"^(abstract|summary|index terms|keywords)\s*(?:[\u2014\u2013:.-]|\s-\s)\s*", re.IGNORECASE
)
NUMBERED_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+[A-Z][^.]{1,80}$")
CAPTION_RE = re.compile(r"^(?:table|fig\.?|figure|algorithm|listing)\s*[0-9IVX]+[.:]?", re.I)

ABBREVIATIONS = {
    "al", "e.g", "i.e", "eg", "ie", "etc", "fig", "figs", "eq", "eqs", "sec", "secs", "tab",
    "no", "nos", "vs", "cf", "dr", "mr", "ms", "prof", "approx", "resp", "ref", "refs", "vol",
    "pp", "ch", "inc", "ltd", "jr", "sr", "st", "dept", "univ", "min", "max", "avg", "std",
}  # fmt: skip
SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s+")

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
ARXIV_STAMP_RE = re.compile(r"arXiv:\S+\s+\[[^\]]+\]\s+\d{1,2}\s+[A-Za-z]{3,}\s+(\d{4})")
NOT_AUTHOR = re.compile(
    r"universit|institut|department|dept\.|school|college|laborator|\blab\b|research|center|"
    r"centre|inc\.|corp|@|e-?mail|abstract|faculty|hospital|street|road|china|usa|germany|"
    r"canada|japan|india|kingdom|france|italy|spain|netherlands|australia|\d{3,}",
    re.IGNORECASE,
)
BAD_META_TITLE = re.compile(r"microsoft|\.docx?|\.tex|untitled|^\s*$|\.pdf|latex", re.I)


@dataclass
class Line:
    page: int
    text: str
    chars: list[tuple[str, Rect]]
    bbox: Rect
    size: float
    bold: bool


@dataclass
class Block:
    page: int
    bbox: Rect
    lines: list[Line]

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines).strip()


@dataclass
class Passage:
    label: str
    page: int
    ordinal: int  # position in the paper, from 0
    section: str  # heading text as written, or "" before the first heading
    section_kind: str  # canonical kind (abstract, method, ...) or other / front
    kind: str  # sentence | caption | reference
    text: str
    rects: list[Rect]

    @property
    def citable(self) -> bool:
        return self.kind != "reference"


@dataclass
class Section:
    title: str
    kind: str
    page: int
    first_ordinal: int


@dataclass
class Metadata:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    source: dict[str, str] = field(default_factory=dict)  # field -> pdf_metadata | first_page


@dataclass
class ParsedPaper:
    page_count: int
    page_sizes: list[tuple[float, float]]
    needs_ocr: bool
    metadata: Metadata
    sections: list[Section]
    passages: list[Passage]
    char_count: int
    removed_lines: int  # headers, footers and page numbers dropped


def parse_pdf(path: Path | str) -> ParsedPaper:
    with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
        return parse_document(doc)


def parse_bytes(data: bytes) -> ParsedPaper:
    with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
        return parse_document(doc)


def parse_document(doc: Any) -> ParsedPaper:
    pages = [_read_page(page, i + 1) for i, page in enumerate(doc)]
    sizes = [(round(p.rect.width, 1), round(p.rect.height, 1)) for p in doc]
    char_count = sum(len(line.text) for blocks in pages for b in blocks for line in b.lines)
    if not pages or char_count < MIN_CHARS_PER_PAGE * len(pages):
        return ParsedPaper(len(pages), sizes, True, _pdf_metadata(doc), [], [], char_count, 0)

    pages, removed = _drop_running_lines(pages, sizes)
    ordered = [_reading_order(blocks, sizes[i][0]) for i, blocks in enumerate(pages)]
    body_size = _body_font_size(b for blocks in ordered for b in blocks)

    b = _Builder()
    for page_no, blocks in enumerate(ordered, start=1):
        b.start_page(page_no)
        line_offset = 0
        for block in blocks:
            text = block.text
            heading = _heading(block, text, body_size)
            if heading is not None:
                b.start_section(*heading)
                continue
            chars = _block_chars(block, line_offset)
            line_offset += len(block.lines)
            size = max(line.size for line in block.lines)
            inline = INLINE_HEADING_RE.match(_text(chars))
            if inline:
                word = inline.group(1).lower()
                kind = "keywords" if word in ("index terms", "keywords") else "abstract"
                b.start_section(inline.group(1).strip().title(), kind)
                chars = _strip_prefix(chars, len(inline.group(0)))
            if _is_equation(text):
                continue
            if b.section_kind == "references":
                b.flush()
                joined = _text(chars)
                if _alpha_count(joined) >= 3:
                    b.add(joined, _rects(chars), "reference")
                continue
            if CAPTION_RE.match(text):
                b.flush()
                b.add(_text(chars)[: MAX_PASSAGE_CHARS * 2], _rects(chars), "caption")
                continue
            b.paragraph(chars, size)
        b.flush()

    passages, sections = b.passages, b.sections
    metadata = _metadata(doc, ordered, body_size, sections)
    return ParsedPaper(len(pages), sizes, False, metadata, sections, passages, char_count, removed)


class _Builder:
    """Collects passages in reading order. A paragraph can continue into the next block (a
    column break, or a block PyMuPDF split), so text is held in `pending` until it ends."""

    def __init__(self) -> None:
        self.passages: list[Passage] = []
        self.sections: list[Section] = []
        self.section, self.section_kind = "", "front"
        self.page = self.on_page = 0
        self.pending: list[Char] = []
        self.pending_size = 0.0

    def start_page(self, page_no: int) -> None:
        self.page, self.on_page = page_no, 0

    def start_section(self, title: str, kind: str) -> None:
        self.flush()
        self.section, self.section_kind = title, kind
        self.sections.append(Section(title, kind, self.page, len(self.passages)))

    def add(self, text: str, rects: list[Rect], kind: str) -> None:
        self.on_page += 1
        self.passages.append(
            Passage(
                f"P{self.page}-S{self.on_page}",
                self.page,
                len(self.passages),
                self.section,
                self.section_kind,
                kind,
                text,
                rects,
            )
        )

    def paragraph(self, chars: list[Char], size: float) -> None:
        if self.pending and _continues(self.pending, self.pending_size, size):
            self.pending = _join(self.pending, chars)
        else:
            self.flush()
            self.pending, self.pending_size = chars, size

    def flush(self) -> None:
        for sentence in _sentences(self.pending):
            self.add(_text(sentence), _rects(sentence), "sentence")
        self.pending = []


# --- reading ---------------------------------------------------------------------------------


def _read_page(page: Any, page_no: int) -> list[Block]:
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    blocks: list[Block] = []
    for b in raw["blocks"]:
        if b.get("type") != 0:
            continue
        lines: list[Line] = []
        for ln in b["lines"]:
            if abs(ln["dir"][1]) > 0.1:  # rotated text, e.g. the arXiv stamp in the margin
                continue
            chars: list[tuple[str, Rect]] = []
            sizes: list[float] = []
            bold = True
            for span in ln["spans"]:
                span_chars = [(c["c"], tuple(c["bbox"])) for c in span["chars"]]
                chars.extend(span_chars)
                sizes.extend([span["size"]] * len(span_chars))
                if span_chars and any(not ch.isspace() for ch, _ in span_chars):
                    bold = bold and bool(span["flags"] & 16 or "bold" in span["font"].lower())
            text = "".join(c for c, _ in chars)
            if not text.strip():
                continue
            # Trim surrounding whitespace characters so rectangles hug the text.
            while chars and chars[0][0].isspace():
                chars.pop(0)
            while chars and chars[-1][0].isspace():
                chars.pop()
            lines.append(
                Line(
                    page_no,
                    "".join(c for c, _ in chars),
                    chars,
                    tuple(ln["bbox"]),
                    max(sizes) if sizes else 0.0,
                    bold,
                )
            )
        if lines:
            blocks.extend(_split_block(page_no, lines))
    return blocks


def _split_block(page_no: int, lines: list[Line]) -> list[Block]:
    """Split a block where PyMuPDF merged a heading with the paragraph below it."""
    out: list[list[Line]] = [[]]
    for i, line in enumerate(lines):
        if out[-1] and i > 0:
            prev = lines[i - 1]
            size_jump = abs(line.size - prev.size) > 0.6
            weight_change = prev.bold != line.bold and len(prev.text) < 90
            if size_jump or weight_change:
                out.append([])
        out[-1].append(line)
    return [Block(page_no, _union([ln.bbox for ln in group]), group) for group in out if group]


def _union(rects: Sequence[Rect]) -> Rect:
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def _normalise_running(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _drop_running_lines(
    pages: list[list[Block]], sizes: list[tuple[float, float]]
) -> tuple[list[list[Block]], int]:
    """Remove running headers and footers: margin lines that repeat on most pages, and page
    numbers on their own in the margin."""

    def in_margin(line: Line, page_no: int) -> bool:
        height = sizes[page_no - 1][1]
        mid = (line.bbox[1] + line.bbox[3]) / 2
        return mid < height * MARGIN_SHARE or mid > height * (1 - MARGIN_SHARE)

    seen: Counter[str] = Counter()
    for blocks in pages:
        keys = {
            _normalise_running(line.text)
            for b in blocks
            for line in b.lines
            if in_margin(line, line.page)
        }
        seen.update(keys)
    n = len(pages)
    repeated = {k for k, c in seen.items() if c >= max(2, n * 0.5)}

    removed = 0
    out: list[list[Block]] = []
    for blocks in pages:
        kept_blocks: list[Block] = []
        for b in blocks:
            kept = []
            for line in b.lines:
                margin = in_margin(line, line.page)
                key = _normalise_running(line.text)
                page_number = re.fullmatch(r"(?:page\s*)?#(?:\s*(?:of|/)\s*#)?", key) is not None
                if margin and (key in repeated or page_number):
                    removed += 1
                else:
                    kept.append(line)
            if kept:
                kept_blocks.append(Block(b.page, _union([ln.bbox for ln in kept]), kept))
        out.append(kept_blocks)
    return out, removed


def _reading_order(blocks: list[Block], width: float) -> list[Block]:
    """Order blocks for reading. On two-column pages: left column, then right column, within
    each band between full-width blocks."""
    mid = width / 2
    tol = width * 0.03

    def side(b: Block) -> str:
        if b.bbox[2] <= mid + tol:
            return "L"
        if b.bbox[0] >= mid - tol:
            return "R"
        return "F"

    sides = [side(b) for b in blocks]
    left_n, right_n = sides.count("L"), sides.count("R")
    if right_n == 0 or left_n == 0:
        return sorted(blocks, key=lambda b: (round(b.bbox[1]), b.bbox[0]))

    full = sorted((b for b, s in zip(blocks, sides, strict=True) if s == "F"),
                  key=lambda b: b.bbox[1])  # fmt: skip
    bands: list[list[Block]] = [[] for _ in range(len(full) + 1)]
    for b, s in zip(blocks, sides, strict=True):
        if s == "F":
            continue
        k = sum(1 for f in full if f.bbox[3] <= b.bbox[1] + 2)
        bands[k].append(b)
    ordered: list[Block] = []
    for k, band in enumerate(bands):
        ordered += sorted((b for b in band if side(b) == "L"), key=lambda b: b.bbox[1])
        ordered += sorted((b for b in band if side(b) == "R"), key=lambda b: b.bbox[1])
        if k < len(full):
            ordered.append(full[k])
    return ordered


def _body_font_size(blocks: Iterable[Block]) -> float:
    weights: Counter[float] = Counter()
    for b in blocks:
        for line in b.lines:
            weights[round(line.size, 1)] += len(line.text)
    return weights.most_common(1)[0][0] if weights else 10.0


def _heading(block: Block, text: str, body_size: float) -> tuple[str, str] | None:
    if len(block.lines) > 2 or len(text) > 90:
        return None
    clean = re.sub(r"\s+", " ", text).strip()
    size = max(line.size for line in block.lines)
    bold = all(line.bold for line in block.lines)
    emphasised = bold or size > body_size * 1.05 or (clean.isupper() and len(clean) > 3)
    for kind, pattern in HEADING_RE:
        if pattern.match(clean) and (emphasised or len(clean) < 30):
            return clean.rstrip(":."), kind
    if emphasised and NUMBERED_HEADING_RE.match(clean) and not clean.endswith("."):
        return clean, _kind_from_words(clean)
    return None


def _kind_from_words(title: str) -> str:
    words = re.sub(rf"^{NUMBERING}", "", title).lower()
    for kind, pattern in SECTION_WORDS:
        if re.search(rf"\b(?:{pattern})\b", words):
            return kind
    return "other"


def _is_equation(text: str) -> bool:
    letters = sum(ch.isalpha() for ch in text)
    return len(text) >= 4 and letters / len(text) < 0.35 and not CAPTION_RE.match(text)


def _alpha_count(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


# --- passages --------------------------------------------------------------------------------


def _block_chars(block: Block, line_offset: int = 0) -> list[Char]:
    out: list[Char] = []
    for i, line in enumerate(block.lines, start=line_offset):
        out = _join(out, [(c, r, i) for c, r in line.chars])
    # Collapse runs of whitespace into one space.
    collapsed: list[Char] = []
    for ch in out:
        if ch[0].isspace():
            if collapsed and collapsed[-1][0] == " ":
                continue
            ch = (" ", ch[1], ch[2])
        collapsed.append(ch)
    return collapsed


HYPHENS = "-\u00ad\u2010"
TERMINAL = re.compile(r"[.!?:][\"'\u201d\u2019)\]]*$")


def _join(left: list[Char], right: list[Char]) -> list[Char]:
    """Join two lines or blocks, undoing a hyphenated break ("evalu-" + "ation")."""
    if not left:
        return list(right)
    if not right:
        return left
    last, before, first = left[-1][0], (left[-2][0] if len(left) > 1 else ""), right[0][0]
    if last in HYPHENS and before.isalpha() and (first.islower() or last != "-"):
        return left[:-1] + right
    return [*left, (" ", None, right[0][2]), *right]


def _continues(pending: list[Char], pending_size: float, size: float) -> bool:
    """Whether a block continues the paragraph collected so far."""
    text = _text(pending)
    return abs(size - pending_size) <= 0.6 and not TERMINAL.search(text)


def _strip_prefix(chars: list[Char], n: int) -> list[Char]:
    rest = chars[n:]
    while rest and rest[0][0] == " ":
        rest = rest[1:]
    return rest


def _text(chars: Sequence[Char]) -> str:
    return "".join(c for c, _, _ in chars).strip()


def _rects(chars: Sequence[Char]) -> list[Rect]:
    by_line: dict[int, list[Rect]] = {}
    for c, r, line in chars:
        if r is None or c.isspace():
            continue
        by_line.setdefault(line, []).append(r)
    return [
        tuple(round(v, 1) for v in _union(rs))  # type: ignore[misc]
        for _, rs in sorted(by_line.items())
    ]


def _sentences(chars: list[Char]) -> list[list[Char]]:
    text = "".join(c for c, _, _ in chars)
    cuts = [0]
    for m in SENTENCE_END.finditer(text):
        end = m.end()
        if end >= len(text):
            continue
        nxt = text[end]
        if not (nxt.isupper() or nxt.isdigit() or nxt in "\"'(\u201c["):
            continue
        token = re.search(r"(\S+)$", text[: m.start()])
        word = token.group(1).lower().lstrip("([\"'") if token else ""
        if (
            word in ABBREVIATIONS
            or re.fullmatch(r"[a-z]", word)
            or re.fullmatch(r"(?:[a-z]\.)+[a-z]", word)
        ):
            continue
        cuts.append(end)
    cuts.append(len(text))
    pieces = [chars[a:b] for a, b in pairwise(cuts)]

    out: list[list[Char]] = []
    for piece in pieces:
        if _alpha_count(_text(piece)) < 3:
            if out:
                out[-1] = out[-1] + piece  # stray fragment such as "1." joins the previous one
            continue
        if out and len(_text(out[-1])) < 25:
            out[-1] = out[-1] + piece  # very short sentence: keep with the next
        else:
            out.append(piece)
    return [p for chunk in out for p in _split_long(chunk)]


def _split_long(chars: list[Char]) -> list[list[Char]]:
    text = "".join(c for c, _, _ in chars)
    if len(text) <= MAX_PASSAGE_CHARS:
        return [chars]
    middle = len(text) // 2
    candidates = [m.end() for m in re.finditer(r"[;:]\s", text)] or [
        m.end() for m in re.finditer(r",\s", text)
    ]
    if not candidates:
        return [chars]
    cut = min(candidates, key=lambda i: abs(i - middle))
    return _split_long(chars[:cut]) + _split_long(chars[cut:])


# --- metadata --------------------------------------------------------------------------------


def _pdf_metadata(doc: Any) -> Metadata:
    meta = doc.metadata or {}
    out = Metadata()
    title = (meta.get("title") or "").strip()
    if len(title) >= 8 and not BAD_META_TITLE.search(title):
        out.title, out.source["title"] = title, "pdf_metadata"
    author = (meta.get("author") or "").strip()
    if author and not BAD_META_TITLE.search(author):
        names = [a.strip() for a in re.split(r";|,|\band\b|&", author) if a.strip()]
        if names:
            out.authors, out.source["authors"] = names, "pdf_metadata"
    created = re.search(r"(19|20)\d{2}", meta.get("creationDate") or "")
    if created:
        out.year, out.source["year"] = int(created.group(0)), "pdf_metadata"
    subject = (meta.get("subject") or "").strip()
    if subject and re.search(
        r"proceedings|conference|journal|transactions|symposium", subject, re.I
    ):
        out.venue, out.source["venue"] = subject, "pdf_metadata"
    return out


def _metadata(
    doc: Any, pages: list[list[Block]], body_size: float, sections: list[Section]
) -> Metadata:
    out = _pdf_metadata(doc)
    first = pages[0] if pages else []
    first_text = "\n".join(b.text for b in first)

    # Front matter: page-one blocks before the first section heading.
    first_section_page_ordinal = next((s for s in sections if s.page == 1), None)
    front: list[Block] = []
    for b in first:
        if first_section_page_ordinal and INLINE_HEADING_RE.match(b.text):
            break
        if any(p.match(re.sub(r"\s+", " ", b.text).strip()) for _, p in HEADING_RE):
            break
        front.append(b)

    title_lines: list[Line] = []
    top = [ln for b in front for ln in b.lines]
    if top:
        biggest = max(ln.size for ln in top)
        if biggest > body_size * 1.15:
            start = next(i for i, ln in enumerate(top) if ln.size >= biggest - 0.5)
            for ln in top[start:]:
                if ln.size < biggest - 0.5:
                    break
                title_lines.append(ln)
    if title_lines and "title" not in out.source:
        title = re.sub(r"\s+", " ", " ".join(ln.text for ln in title_lines)).strip()
        if len(title) >= 8:
            out.title, out.source["title"] = title, "first_page"

    if "authors" not in out.source and title_lines:
        after = top[top.index(title_lines[-1]) + 1 :]
        names: list[str] = []
        for ln in after[:8]:
            text = re.sub(r"[*\u2020\u2021\u00a7\u00b6\d]+", " ", ln.text)
            if NOT_AUTHOR.search(ln.text):
                if names:
                    break
                continue
            parts = [p.strip() for p in re.split(r",|;|\band\b|&", text) if p.strip()]
            looks = [
                p for p in parts if re.fullmatch(r"(?:[A-Z][\w'.\-]*\s+){1,3}[A-Z][\w'\-]+", p)
            ]
            if looks and len(looks) >= len(parts) / 2:
                names += looks
            elif names:
                break
        if names:
            out.authors, out.source["authors"] = names, "first_page"

    stamp = ARXIV_STAMP_RE.search(first_text)
    copyright_year = re.search(r"(?:\u00a9|copyright)\s*(\d{4})", first_text, re.I)
    front_year = YEAR_RE.search("\n".join(b.text for b in front))
    year = stamp or copyright_year or front_year
    if year:
        out.year, out.source["year"] = int(year.group(1)), "first_page"

    early = "\n".join(b.text for blocks in pages[:2] for b in blocks)
    doi = DOI_RE.search(early)
    if doi:
        out.doi, out.source["doi"] = doi.group(1).rstrip(".,;)"), "first_page"
    if "venue" not in out.source:
        venue = re.search(
            r"((?:(?:IEEE|ACM)\s+)?(?:Proceedings of|Journal of|Transactions on)"
            r"[^\n\u00b7|\u00a9]{3,120}?)(?=\s*(?:[\u00b7|\u00a9\n,(]|DOI|$))",
            first_text,
            re.IGNORECASE,
        )
        if venue:
            out.venue, out.source["venue"] = venue.group(1).strip(), "first_page"
    return out


def passage_dict(p: Passage) -> dict[str, Any]:
    return {
        "label": p.label,
        "page": p.page,
        "ordinal": p.ordinal,
        "section": p.section,
        "section_kind": p.section_kind,
        "kind": p.kind,
        "text": p.text,
        "rects": [list(r) for r in p.rects],
    }
