"""Detect columns holding personal data, and mask values before they reach an LLM.

Detection uses the column name and value patterns checked over the whole column with SQL.
Flagged columns never send sample or top values to the LLM; other text is scrubbed of
emails, phone numbers and long digit runs.
"""

import re
from dataclasses import dataclass
from typing import Any

import duckdb

from api.ingest.names import quote

# (reason, pattern on the safe column name)
NAME_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("email address", re.compile(r"e_?mail")),
    ("phone number", re.compile(r"phone|mobile|(^|_)cell(_|$)|(^|_)tel(ephone)?(_|$)|(^|_)fax")),
    (
        "person name",
        re.compile(
            r"^(first|last|full|given|family|middle|maiden|sur|user|respondent|patient|"
            r"participant|student|customer|person|contact|employee|client)_?name$|surname"
        ),
    ),
    ("address", re.compile(r"address|street|postcode|postal|zip_?code|(^|_)zip$")),
    ("birth date", re.compile(r"birth|(^|_)dob(_|$)|birthday")),
    (
        "government ID",
        re.compile(r"ssn|social_security|passport|national_id|(^|_)nin(_|$)|tax_id|driver_?lic"),
    ),
    ("IP address", re.compile(r"(^|_)ip(_?addr(ess)?)?$")),
]
# A bare "name" column is personal only if it looks like a list of individuals.
BARE_NAME_UNIQUENESS = 0.5

# (reason, regex matched against whole values)
VALUE_RULES: list[tuple[str, str]] = [
    ("email address", r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    ("phone number", r"^\+?[0-9]{0,3}[ .-]?\(?[0-9]{2,4}\)?[ .-][0-9]{3,4}[ .-]?[0-9]{3,4}$"),
    ("IP address", r"^([0-9]{1,3}\.){3}[0-9]{1,3}$"),
]
VALUE_SHARE = 0.5

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+?\d[\d ().-]{7,}\d")
DIGITS = re.compile(r"\d{9,}")


@dataclass(frozen=True)
class PiiResult:
    is_pii: bool
    reason: str | None


def detect(
    con: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
    physical_type: str,
    profile: dict[str, Any],
) -> PiiResult:
    for reason, pattern in NAME_RULES:
        if pattern.search(column):
            return PiiResult(True, f"{reason} (column name)")
    if column == "name" and profile.get("uniqueness", 0) >= BARE_NAME_UNIQUENESS:
        return PiiResult(True, "person name (column name, mostly unique values)")

    if physical_type == "VARCHAR" and profile.get("non_null"):
        c = quote(column)
        checks = ", ".join(f"count_if(regexp_full_match(trim({c}), ?))" for _ in VALUE_RULES)
        row = con.execute(
            f"SELECT count({c}), {checks} FROM {quote(table)} WHERE {c} IS NOT NULL",
            [pattern for _, pattern in VALUE_RULES],
        ).fetchone()
        if row and row[0]:
            for (reason, _), matched in zip(VALUE_RULES, row[1:], strict=True):
                if matched / row[0] >= VALUE_SHARE:
                    return PiiResult(True, f"{reason} ({matched / row[0]:.0%} of values)")
    return PiiResult(False, None)


def scrub(text: str) -> str:
    """Mask emails, phone numbers and long digit runs inside free text."""
    text = EMAIL.sub("<email>", text)
    text = PHONE.sub("<phone>", text)
    return DIGITS.sub("<number>", text)
