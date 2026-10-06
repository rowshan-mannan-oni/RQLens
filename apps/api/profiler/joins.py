"""Candidate join keys between tables of the same project.

A column pair is checked when the names match (customer_id = customer_id, or orders.customer_id
to customers.id) or when one side is a key and the other could reference it. The check counts
distinct values found on both sides.
"""

import re
from dataclasses import dataclass
from itertools import product
from typing import Any

import duckdb

from api.ingest.names import quote

MAX_CHECKS = 100
MIN_SHARED = 2
MIN_COVERAGE = 0.5
KEY_UNIQUENESS = 0.95
MIN_UNNAMED_INTEGER_DISTINCT = 20
GENERIC_NAMES = {
    "id",
    "key",
    "code",
    "name",
    "index",
    "idx",
    "row",
    "no",
    "number",
    "value",
    "type",
}
UNIQUE = 0.999
JOINABLE_TYPES = {"identifier", "categorical"}
INTEGER_TYPES = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT",
                 "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT"}  # fmt: skip


@dataclass(frozen=True)
class JoinColumn:
    name: str
    physical_type: str
    semantic_type: str
    distinct: int
    uniqueness: float


@dataclass(frozen=True)
class JoinTable:
    dataset_id: int
    table_name: str
    columns: tuple[JoinColumn, ...]


def _family(physical: str) -> str | None:
    p = physical.upper()
    if p in INTEGER_TYPES:
        return "integer"
    if p == "VARCHAR":
        return "text"
    return None


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def name_match(a: JoinColumn, ta: JoinTable, b: JoinColumn, tb: JoinTable) -> bool:
    # Two tables that both have an "id" column are not evidence of a join.
    if a.name == b.name and a.name not in GENERIC_NAMES:
        return True
    # orders.customer_id <-> customers.id
    for x, y, ty in ((a, b, tb), (b, a, ta)):
        prefix = _singular(re.sub(r"_?\d+$", "", ty.table_name))
        if x.name == f"{prefix}_{y.name}":
            return True
    return False


def _plausible_without_name(a: JoinColumn, b: JoinColumn, fa: str, fb: str) -> bool:
    """Without a name match, overlapping values are often coincidence (two 1..N counters,
    a 1-5 scale against an ID). Require one key side and, for integers, a referencing side
    that is not itself unique and has enough distinct values."""
    if fa != fb:
        return False
    if a.semantic_type not in JOINABLE_TYPES or b.semantic_type not in JOINABLE_TYPES:
        return False
    a_key, b_key = a.uniqueness >= KEY_UNIQUENESS, b.uniqueness >= KEY_UNIQUENESS
    if not (a_key or b_key):
        return False
    if fa == "text":
        return True
    if a_key and b_key:
        return False
    reference = b if a_key else a
    return reference.distinct >= MIN_UNNAMED_INTEGER_DISTINCT


def find_joins(
    con: duckdb.DuckDBPyConnection, new: JoinTable, others: list[JoinTable]
) -> list[dict[str, Any]]:
    candidates: list[tuple[bool, JoinColumn, JoinTable, JoinColumn, JoinTable]] = []
    for other in others:
        for a, b in product(new.columns, other.columns):
            fa, fb = _family(a.physical_type), _family(b.physical_type)
            if fa is None or fb is None:
                continue
            if name_match(a, new, b, other):
                # A matching name is strong evidence, so integer "numeric" columns qualify.
                if {a.semantic_type, b.semantic_type} <= JOINABLE_TYPES | {"numeric"}:
                    candidates.append((True, a, new, b, other))
            elif _plausible_without_name(a, b, fa, fb):
                candidates.append((False, a, new, b, other))
    # Name matches first: they are the most likely real joins.
    candidates.sort(key=lambda c: not c[0])

    out: list[dict[str, Any]] = []
    for named, a, ta, b, tb in candidates[:MAX_CHECKS]:
        row = con.execute(
            f"""
            WITH l AS (SELECT DISTINCT {quote(a.name)}::VARCHAR AS v FROM {quote(ta.table_name)}
                       WHERE {quote(a.name)} IS NOT NULL),
                 r AS (SELECT DISTINCT {quote(b.name)}::VARCHAR AS v FROM {quote(tb.table_name)}
                       WHERE {quote(b.name)} IS NOT NULL)
            SELECT (SELECT count(*) FROM l), (SELECT count(*) FROM r),
                   (SELECT count(*) FROM l JOIN r USING (v))
            """
        ).fetchone()
        if row is None:
            continue
        left, right, shared = (int(x) for x in row)
        if shared < MIN_SHARED or shared / min(left, right) < MIN_COVERAGE:
            continue
        left_unique, right_unique = a.uniqueness >= UNIQUE, b.uniqueness >= UNIQUE
        cardinality = {
            (True, True): "one-to-one",
            (True, False): "one-to-many",
            (False, True): "many-to-one",
            (False, False): "many-to-many",
        }[(left_unique, right_unique)]
        out.append(
            {
                "left_dataset_id": ta.dataset_id,
                "left_column": a.name,
                "right_dataset_id": tb.dataset_id,
                "right_column": b.name,
                "shared_values": shared,
                "left_distinct": left,
                "right_distinct": right,
                "left_coverage": shared / left,
                "right_coverage": shared / right,
                "cardinality": cardinality,
                "name_match": named,
            }
        )
    out.sort(key=lambda j: (not j["name_match"], -min(j["left_coverage"], j["right_coverage"])))
    return out
