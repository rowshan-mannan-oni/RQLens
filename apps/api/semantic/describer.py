"""LLM-written one-line column descriptions.

The model sees column names, types and profile statistics, plus a few sample or frequent
values with personal data masked. It never sees raw rows. Columns described by the user or a
data dictionary are left alone.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from api.llm.client import LLMClient
from api.semantic.pii import scrub

PROMPT_VERSION = "describe_columns.v1"
PROMPT = (Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8"
)
BATCH_SIZE = 30
MAX_VALUES = 5
MAX_VALUE_LENGTH = 60


class ColumnDescription(BaseModel):
    name: str
    description: str = Field(max_length=400)
    confidence: Literal["high", "medium", "low"]


class Descriptions(BaseModel):
    columns: list[ColumnDescription]


def column_evidence(
    name: str,
    original_name: str | None,
    semantic_type: str | None,
    is_pii: bool,
    profile: dict[str, Any],
    share_samples: bool,
) -> dict[str, Any]:
    """What the model may see about one column."""
    out: dict[str, Any] = {
        "name": name,
        "header": original_name or name,
        "type": semantic_type,
        "physical_type": profile.get("physical_type"),
        "missing_pct": round(profile.get("missing_pct", 0) * 100, 1),
        "distinct_values": profile.get("distinct"),
    }
    if is_pii:
        out["personal_data"] = True
        return out

    numeric = profile.get("numeric")
    if numeric and numeric.get("finite"):
        out["min"], out["max"] = numeric["min"], numeric["max"]
        out["median"], out["mean"] = numeric["median"], numeric["mean"]
    dates = profile.get("datetime")
    if dates:
        out["date_range"] = [dates["min"], dates["max"]]
        out["granularity"] = dates["granularity"]
    text = profile.get("text")
    if text:
        out["avg_length"] = round(text["avg_length"], 1)

    if share_samples:
        top = profile.get("top_values")
        if top:
            out["frequent_values"] = [
                {"value": _clip(scrub(str(v["value"]))), "share_pct": round(v["share"] * 100, 1)}
                for v in top[:MAX_VALUES]
            ]
        elif text and text.get("samples"):
            out["sample_values"] = [_clip(scrub(str(s))) for s in text["samples"][:MAX_VALUES]]
    return out


def _clip(value: str) -> str:
    return value if len(value) <= MAX_VALUE_LENGTH else value[: MAX_VALUE_LENGTH - 1] + "…"


async def describe(
    client: LLMClient,
    *,
    filename: str,
    project_topic: str | None,
    columns: list[dict[str, Any]],
    project_id: int,
) -> dict[str, ColumnDescription]:
    """Return descriptions keyed by column name. Columns the model skipped are absent."""
    out: dict[str, ColumnDescription] = {}
    for start in range(0, len(columns), BATCH_SIZE):
        batch = columns[start : start + BATCH_SIZE]
        payload = {
            "file": filename,
            "research_topic": project_topic,
            "columns": batch,
        }
        result = await client.complete_structured(
            [
                {"role": "system", "content": PROMPT},
                {
                    "role": "user",
                    "content": "<dataset>\n"
                    + json.dumps(payload, ensure_ascii=False, default=str)
                    + "\n</dataset>",
                },
            ],
            Descriptions,
            step="describe_columns",
            prompt_version=PROMPT_VERSION,
            project_id=project_id,
        )
        assert result.parsed is not None
        wanted = {c["name"] for c in batch}
        for d in result.parsed.columns:
            if d.name in wanted:
                out[d.name] = d
    return out
