"""Read reference files (BibTeX, RIS) and match their entries to uploaded papers.

Zotero, Mendeley and EndNote all export BibTeX or RIS. An entry gives a paper its title,
authors, year, venue, DOI and citation key; entries are matched to papers by DOI, then by
title. Entries with no paper yet are kept, and matched when their PDF is uploaded. The file
paths in an export (Zotero's `file` field, RIS `L1`) are listed so the researcher knows which
PDFs to upload: the server cannot read their disk.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

TITLE_MATCH = 0.92

LATEX_ACCENTS = {
    '"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303", "c": "\u0327",
    "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b", "r": "\u030a",
}  # fmt: skip
LATEX_LETTERS = {
    "ss": "\u00df", "o": "\u00f8", "O": "\u00d8", "ae": "\u00e6", "AE": "\u00c6",
    "aa": "\u00e5", "AA": "\u00c5", "l": "\u0142", "L": "\u0141",
}  # fmt: skip


@dataclass
class Reference:
    key: str
    kind: str  # article, inproceedings, ... (BibTeX) or JOUR, CONF, ... (RIS)
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    files: list[str] = field(default_factory=list)


# --- BibTeX ----------------------------------------------------------------------------------


def parse_bibtex(text: str) -> list[Reference]:
    out = []
    for kind, body in _bib_entries(text):
        if kind.lower() in ("comment", "preamble", "string"):
            continue
        key, _, rest = body.partition(",")
        fields = _bib_fields(rest)
        venue = next(
            (fields[f] for f in ("journal", "booktitle", "journaltitle", "publisher", "school")
             if fields.get(f)),
            None,
        )  # fmt: skip
        out.append(
            Reference(
                key=key.strip(),
                kind=kind.lower(),
                title=_clean(fields.get("title")),
                authors=_bib_authors(fields.get("author", "")),
                year=_year(fields.get("year") or fields.get("date")),
                venue=_clean(venue),
                doi=_doi(fields.get("doi") or fields.get("url")),
                files=_bib_files(fields.get("file", "")),
            )
        )
    return out


def _bib_entries(text: str) -> Iterable[tuple[str, str]]:
    i = 0
    while True:
        m = re.compile(r"@(\w+)\s*([{(])").search(text, i)
        if not m:
            return
        open_ch = m.group(2)
        close_ch = "}" if open_ch == "{" else ")"
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text[j] == open_ch:
                depth += 1
            elif text[j] == close_ch:
                depth -= 1
            j += 1
        yield m.group(1), text[m.end() : j - 1]
        i = j


def _bib_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i = 0
    name_re = re.compile(r"\s*,?\s*([A-Za-z][\w\-]*)\s*=\s*")
    while True:
        m = name_re.match(text, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i < len(text) and text[i] in '{"':
            close = "}" if text[i] == "{" else '"'
            depth, j = 1, i + 1
            while j < len(text) and depth:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[i] == "{" and text[j] == "{":
                    depth += 1
                elif text[j] == close:
                    depth -= 1
                j += 1
            value = text[i + 1 : j - 1]
            i = j
        else:
            m2 = re.compile(r"[^,}]*").match(text, i)
            value = m2.group(0).strip() if m2 else ""
            i = m2.end() if m2 else len(text)
        # "a" # "b" concatenation is rare in exports; keep the first part.
        fields[name] = value
    return fields


def latex_to_text(s: str) -> str:
    def accent(m: re.Match[str]) -> str:
        return unicodedata.normalize("NFC", m.group(2) + LATEX_ACCENTS[m.group(1)])

    s = re.sub(r"\\([\"'`^~c=.uvHr])\s*\{?\s*([A-Za-z])\}?", accent, s)
    s = re.sub(
        r"\{?\\(ss|ae|AE|aa|AA|o|O|l|L)(?![A-Za-z])\}?\s?",
        lambda m: LATEX_LETTERS[m.group(1)],
        s,
    )
    s = re.sub(r"\\([&%_$#])", r"\1", s)
    s = s.replace("---", "\u2014").replace("--", "\u2013").replace("~", " ")
    s = re.sub(r"\\(?:emph|textit|textbf|textsc|mathrm|text)\s*", "", s)
    return s.replace("{", "").replace("}", "")


def _clean(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", latex_to_text(s)).strip()
    return s or None


def _bib_authors(s: str) -> list[str]:
    names = []
    for part in re.split(r"\s+and\s+", latex_to_text(s)):
        part = re.sub(r"\s+", " ", part).strip()
        if not part or part.lower() == "others":
            continue
        if "," in part:  # "Last, First" or "Last, Jr, First"
            pieces = [p.strip() for p in part.split(",")]
            part = " ".join([*pieces[1:], pieces[0]]).strip()
        names.append(part)
    return names


def _bib_files(s: str) -> list[str]:
    # Zotero: "Full Text PDF:files/12/paper.pdf:application/pdf;..."
    out = []
    for item in s.split(";"):
        parts = item.split(":")
        path = next((p for p in parts if p.lower().endswith(".pdf")), None)
        if path:
            out.append(path.replace("\\", "/").split("/")[-1])
    return out


# --- RIS -------------------------------------------------------------------------------------


def parse_ris(text: str) -> list[Reference]:
    out: list[Reference] = []
    cur: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - ?(.*)$", line.rstrip())
        if not m:
            continue
        tag, value = m.group(1), m.group(2).strip()
        if tag == "ER":
            if cur:
                out.append(_ris_reference(cur, len(out) + 1))
            cur = {}
            continue
        cur.setdefault(tag, []).append(value)
    if cur:
        out.append(_ris_reference(cur, len(out) + 1))
    return out


def _ris_reference(f: dict[str, list[str]], n: int) -> Reference:
    def first(*tags: str) -> str | None:
        return next((f[t][0] for t in tags if f.get(t) and f[t][0]), None)

    authors = []
    for a in f.get("AU", []) + f.get("A1", []):
        if "," in a:
            last, _, given = a.partition(",")
            a = f"{given.strip()} {last.strip()}".strip()
        authors.append(a)
    files = [v.replace("\\", "/").split("/")[-1] for t in ("L1", "L4") for v in f.get(t, [])]
    return Reference(
        key=first("ID") or f"ris{n}",
        kind=first("TY") or "GEN",
        title=_clean(first("TI", "T1", "CT")),
        authors=authors,
        year=_year(first("PY", "Y1", "DA")),
        venue=_clean(first("T2", "JO", "JF", "JA", "BT", "PB")),
        doi=_doi(first("DO", "UR")),
        files=[x for x in files if x.lower().endswith(".pdf")],
    )


# --- shared ----------------------------------------------------------------------------------


def parse_references(text: str, filename: str) -> list[Reference]:
    if filename.lower().endswith(".ris") or re.search(r"^TY  - ", text, re.M):
        return parse_ris(text)
    return parse_bibtex(text)


def _year(s: str | None) -> int | None:
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", s or "")
    return int(m.group(1)) if m else None


def _doi(s: str | None) -> str | None:
    m = re.search(r"(10\.\d{4,9}/[^\s\"<>{}]+)", s or "", re.I)
    return m.group(1).rstrip(".,;)").lower() if m else None


def title_key(title: str | None) -> str:
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def match(ref: Any, papers: Sequence[Any]) -> Any | None:
    """The paper an entry describes: same DOI, or a title at least TITLE_MATCH similar.
    `ref` and `papers` need `doi` and `title` attributes."""
    if ref.doi:
        for p in papers:
            if p.doi and p.doi.lower() == ref.doi:
                return p
    key = title_key(ref.title)
    if len(key) < 10:
        return None
    best, best_score = None, 0.0
    for p in papers:
        other = title_key(p.title)
        if not other:
            continue
        score = 1.0 if key == other else SequenceMatcher(None, key, other).ratio()
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= TITLE_MATCH else None


def apply_to_paper(paper: Any, entry: Any) -> list[str]:
    """Copy an entry's metadata onto a paper, except fields the user corrected. Returns the
    fields changed."""
    sources = dict(paper.metadata_source_json or {})
    changed = []
    values = {
        "title": entry.title,
        "authors": entry.authors_json or None,
        "year": entry.year,
        "venue": entry.venue,
        "doi": entry.doi,
    }
    for name, value in values.items():
        if value is None or sources.get(name) == "user":
            continue
        if name == "authors":
            paper.authors_json = value
        else:
            setattr(paper, name, value)
        sources[name] = "reference"
        changed.append(name)
    paper.metadata_source_json = sources
    paper.cite_key = entry.cite_key
    return changed
