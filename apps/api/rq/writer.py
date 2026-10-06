"""Step 4b and 5: explain a decided verdict, and suggest questions the data can answer.

The explanation may only quote numbers that appear in the measurements; it is checked with the
same grounding check as chat answers, sent back once if it fails, then flagged.
"""

import json
from pathlib import Path
from typing import Any

from api.agent import grounding
from api.agent.tools import ProjectContext
from api.llm.client import LLMClient
from api.rq.mapper import schema_for
from api.rq.schemas import Mapping, ParsedRQ, RuleResult, Suggestion, Suggestions, Verdict, Writeup
from api.semantic.column_retrieval import ColumnRetriever

PROMPTS = Path(__file__).parent.parent / "prompts"
EXPLAIN_VERSION = "rq_explain.v1"
SUGGEST_VERSION = "rq_suggest.v1"


def assessment_payload(
    parsed: ParsedRQ,
    mapping: Mapping,
    verdict: Verdict,
    rules: list[RuleResult],
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "question_type": parsed.type,
        "population": parsed.population,
        "constructs": [
            {
                "name": c.name,
                "role": c.role,
                "mapped_to": (
                    None
                    if c.status == "rejected" or not c.candidates
                    else {
                        "table": c.candidates[0].table,
                        "column": c.candidates[0].column,
                        "expression": c.candidates[0].expression,
                        "match": c.candidates[0].match,
                    }
                ),
            }
            for c in mapping.constructs
        ],
        "population_filter": mapping.population_filter,
        "checks": [{"rule": r.rule, "level": r.level, "message": r.message} for r in rules],
        "facts": [f["message"] for f in facts],
    }


async def explain(
    client: LLMClient,
    text: str,
    payload: dict[str, Any],
    project_id: int | None = None,
) -> tuple[Writeup, dict[str, Any]]:
    """The write-up, and its grounding result."""
    pool = grounding.collect_numbers(payload, text)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": (PROMPTS / f"{EXPLAIN_VERSION}.md").read_text("utf-8")},
        {
            "role": "user",
            "content": f"<research_question>\n{text}\n</research_question>\n<assessment>\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
            + "\n</assessment>",
        },
    ]
    check: grounding.GroundingResult | None = None
    writeup: Writeup | None = None
    for attempt in range(2):
        result = await client.complete_structured(
            messages,
            Writeup,
            step="rq_explain",
            prompt_version=EXPLAIN_VERSION,
            project_id=project_id,
        )
        assert result.parsed is not None
        writeup = result.parsed
        check = grounding.check(_all_text(writeup), pool)
        if check.ok or attempt == 1:
            break
        messages += [
            {"role": "assistant", "content": result.text},
            {
                "role": "user",
                "content": "These numbers do not appear in the assessment: "
                + ", ".join(check.unsupported)
                + ". Remove them or use numbers from the assessment, and reply again.",
            },
        ]
    assert writeup is not None and check is not None
    if payload["verdict"] == "answerable":
        writeup = writeup.model_copy(update={"rewording": None})
    return writeup, check.to_json()


def _all_text(w: Writeup) -> str:
    return "\n".join([w.explanation, w.suggested_method, *w.threats, w.rewording or ""])


def fallback_writeup(verdict: Verdict, rules: list[RuleResult]) -> Writeup:
    """Used when the LLM is unavailable: the rule messages, verbatim."""
    reasons = [r.message for r in rules if r.level in ("fail", "warn")]
    lead = {
        "answerable": "The data looks able to answer this question.",
        "partial": "The data can answer this question only in part.",
        "not_answerable": "The data cannot answer this question as worded.",
    }[verdict]
    return Writeup(
        explanation=" ".join([lead, *reasons])[:1500],
        suggested_method="",
        threats=[],
        rewording=None,
    )


async def suggest(
    client: LLMClient,
    ctx: ProjectContext,
    existing: list[str],
    retriever: ColumnRetriever | None = None,
    project_id: int | None = None,
) -> list[Suggestion]:
    schema = await schema_for(ctx, " ".join([ctx.topic or "", *existing]), retriever)
    content = (
        f"<topic>\n{ctx.topic or ''}\n</topic>\n"
        f"<existing_questions>\n{json.dumps(existing, ensure_ascii=False)}\n"
        "</existing_questions>\n"
        f"<schema>\n{json.dumps(schema, ensure_ascii=False, default=str)}\n</schema>"
    )
    result = await client.complete_structured(
        [
            {"role": "system", "content": (PROMPTS / f"{SUGGEST_VERSION}.md").read_text("utf-8")},
            {"role": "user", "content": content},
        ],
        Suggestions,
        step="rq_suggest",
        prompt_version=SUGGEST_VERSION,
        project_id=project_id,
    )
    assert result.parsed is not None
    known = {
        f"{t.table}.{c.name}".lower(): f"{t.table}.{c.name}" for t in ctx.tables for c in t.columns
    }
    out = []
    for s in result.parsed.suggestions:
        columns = [known[c.lower()] for c in s.columns if c.lower() in known]
        if columns:  # a suggestion naming no real column is dropped
            out.append(s.model_copy(update={"columns": columns}))
    return out
