"""Compare several profiled tables: which columns they share and where they disagree.

Works on stored profiles only; no query runs. Columns are matched by name, ignoring case and
punctuation ("Age (yrs)" matches "age_yrs").
"""

from dataclasses import dataclass
from typing import Any

UNIT_RATIO = 2.0
MISSING_GAP = 0.3
CATEGORY_OVERLAP = 0.5


@dataclass(frozen=True)
class CompareColumn:
    name: str
    original_name: str
    physical_type: str
    semantic_type: str
    profile: dict[str, Any]


@dataclass(frozen=True)
class CompareTable:
    dataset_id: int
    label: str
    row_count: int
    columns: tuple[CompareColumn, ...]


def match_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


KIND_LABEL = {"numeric": "number", "text": "text", "datetime": "date", "boolean": "true/false"}


def compare(tables: list[CompareTable]) -> dict[str, Any]:
    by_key: dict[str, dict[int, CompareColumn]] = {}
    order: list[str] = []
    for t in tables:
        for c in t.columns:
            key = match_key(c.original_name or c.name)
            if key not in by_key:
                by_key[key] = {}
                order.append(key)
            by_key[key].setdefault(t.dataset_id, c)

    labels = {t.dataset_id: t.label for t in tables}
    columns: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for key in order:
        present = by_key[key]
        first = next(iter(present.values()))
        label = first.original_name or first.name
        cells = {
            str(dataset_id): {
                "name": c.name,
                "original_name": c.original_name,
                "physical_type": c.physical_type,
                "semantic_type": c.semantic_type,
                "kind": c.profile.get("kind"),
                "missing_pct": c.profile.get("missing_pct"),
                "distinct": c.profile.get("distinct"),
                "median": (c.profile.get("numeric") or {}).get("median"),
            }
            for dataset_id, c in present.items()
        }
        column_issues = _issues(label, present, labels) if len(present) > 1 else []
        issues += column_issues
        columns.append(
            {
                "key": key,
                "label": label,
                "in_all": len(present) == len(tables),
                "cells": cells,
                "issues": [i["code"] for i in column_issues],
            }
        )

    shared = sum(1 for c in columns if c["in_all"])
    return {
        "tables": [
            {
                "dataset_id": t.dataset_id,
                "label": t.label,
                "row_count": t.row_count,
                "column_count": len(t.columns),
            }
            for t in tables
        ],
        "columns": columns,
        "issues": issues,
        "shared_columns": shared,
        "total_columns": len(columns),
        # Stacking makes sense when most columns line up across the files.
        "stackable": len(tables) > 1 and shared > 0 and shared / len(columns) >= 0.5,
    }


def _issues(
    label: str, present: dict[int, CompareColumn], labels: dict[int, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    kinds = {i: c.profile.get("kind") for i, c in present.items()}
    if len(set(kinds.values())) > 1:
        detail = ", ".join(f"{KIND_LABEL.get(k or '', k)} in {labels[i]}" for i, k in kinds.items())
        out.append(
            {
                "code": "type_mismatch",
                "column": label,
                "message": f"'{label}' has different types across files: {detail}.",
            }
        )
        return out

    # Identifiers have no scale: different ID ranges per file are expected.
    medians = {
        i: (c.profile.get("numeric") or {}).get("median")
        for i, c in present.items()
        if c.profile.get("numeric") and c.semantic_type != "identifier"
    }
    values = [abs(m) for m in medians.values() if m]
    if len(values) > 1 and max(values) / min(values) >= UNIT_RATIO:
        detail = ", ".join(f"{m:.4g} in {labels[i]}" for i, m in medians.items() if m is not None)
        out.append(
            {
                "code": "scale_mismatch",
                "column": label,
                "message": f"'{label}' has very different medians ({detail}); the files may "
                "use different units or scales.",
            }
        )

    tops = {
        i: {str(v["value"]).strip().lower() for v in c.profile.get("top_values", [])}
        for i, c in present.items()
        if c.semantic_type in ("categorical", "boolean") and c.profile.get("top_values")
    }
    if len(tops) > 1:
        sets = list(tops.values())
        union, common = set.union(*sets), set.intersection(*sets)
        if union and len(common) / len(union) < CATEGORY_OVERLAP:
            examples = "; ".join(
                f"{labels[i]}: " + ", ".join(sorted(s)[:4]) for i, s in tops.items()
            )
            out.append(
                {
                    "code": "category_mismatch",
                    "column": label,
                    "message": f"'{label}' uses different categories across files ({examples}). "
                    "Recode them before comparing or stacking.",
                }
            )

    missing = {i: c.profile.get("missing_pct") or 0.0 for i, c in present.items()}
    if max(missing.values()) - min(missing.values()) >= MISSING_GAP:
        detail = ", ".join(f"{m:.0%} in {labels[i]}" for i, m in missing.items())
        out.append(
            {
                "code": "missing_gap",
                "column": label,
                "message": f"'{label}' is missing much more often in some files ({detail}).",
            }
        )
    return out
