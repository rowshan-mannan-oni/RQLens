"""Parse an uploaded data dictionary (CSV) and match its rows to dataset columns."""

import csv
import io
from dataclasses import dataclass

NAME_HEADERS = ("column", "variable", "field", "name", "column_name", "variable_name", "var")
DESCRIPTION_HEADERS = (
    "description", "label", "definition", "meaning", "variable_label", "question", "notes",
)  # fmt: skip
MAX_DESCRIPTION = 2000


class DictionaryError(ValueError):
    pass


@dataclass(frozen=True)
class DictionaryEntry:
    name: str
    description: str


def parse_dictionary(raw: bytes) -> list[DictionaryEntry]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = {h.strip().lower(): h for h in reader.fieldnames or []}

    name_key = next((headers[h] for h in NAME_HEADERS if h in headers), None)
    desc_key = next((headers[h] for h in DESCRIPTION_HEADERS if h in headers), None)
    if name_key is None or desc_key is None:
        raise DictionaryError(
            "The dictionary needs a column-name column (for example 'column' or 'variable') "
            "and a description column (for example 'description' or 'label')."
        )

    entries = []
    for row in reader:
        name = (row.get(name_key) or "").strip()
        description = (row.get(desc_key) or "").strip()
        if name and description:
            entries.append(DictionaryEntry(name, description[:MAX_DESCRIPTION]))
    return entries


def _key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def match_entries(
    entries: list[DictionaryEntry], columns: list[tuple[str, str | None]]
) -> tuple[dict[str, str], list[str]]:
    """Match entries to columns by original header or safe name, ignoring case and punctuation.

    `columns` is a list of (safe name, original header). Returns ({safe name: description},
    unmatched entry names).
    """
    lookup: dict[str, str] = {}
    for safe, original in columns:
        lookup.setdefault(_key(safe), safe)
        if original:
            lookup[_key(original)] = safe
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for e in entries:
        target = lookup.get(_key(e.name))
        if target is None:
            unmatched.append(e.name)
        else:
            matched[target] = e.description
    return matched, unmatched
