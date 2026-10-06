"""Assess one research question: parse, map, measure, decide, explain.

Parse and map are skipped when the caller passes a parsed question or a mapping (for example a
mapping the user edited). The verdict comes from the rules alone; if the LLM fails while writing
the explanation, the rule messages are used instead, so a verdict is never lost.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from api.agent.tools import ProjectContext
from api.llm.client import LLMClient
from api.rq import mapper, writer
from api.rq.feasibility import Execute, measure
from api.rq.schemas import Mapping, ParsedRQ, RuleResult, Verdict, Writeup
from api.rq.verdict import RULES_VERSION, apply_rules, decide
from api.semantic.column_retrieval import ColumnRetriever

log = logging.getLogger(__name__)

CONFIG_VERSION = (
    f"{mapper.PARSE_VERSION}+{mapper.MAP_VERSION}+{writer.EXPLAIN_VERSION}+{RULES_VERSION}"
)


@dataclass
class Assessment:
    parsed: ParsedRQ
    mapping: Mapping
    verdict: Verdict
    rules: list[RuleResult]
    facts: list[dict[str, Any]]
    writeup: Writeup
    grounding: dict[str, Any] | None
    explained_by: str  # llm | rules
    problems: list[str] = field(default_factory=list)  # mapping fixes and failed checks
    query_ids: list[int] = field(default_factory=list)

    def gaps(self) -> list[dict[str, str]]:
        return [
            {"construct": c.name, "role": c.role}
            for c in self.mapping.constructs
            if c.status == "rejected" or not c.candidates
        ]


async def assess(
    client: LLMClient,
    ctx: ProjectContext,
    text: str,
    execute: Execute,
    *,
    parsed: ParsedRQ | None = None,
    mapping: Mapping | None = None,
    associations: Sequence[dict[str, Any]] = (),
    retriever: ColumnRetriever | None = None,
) -> Assessment:
    pid = ctx.project_id or None
    problems: list[str] = []
    if parsed is None:
        parsed = await mapper.parse(client, text, ctx.topic, pid)
        mapping = None  # a new parse invalidates any mapping
    if mapping is None:
        mapping, problems = await mapper.map_constructs(client, ctx, text, parsed, retriever, pid)
    else:
        mapping, problems = mapper.validate(ctx, mapping)

    report = await measure(ctx, parsed, mapping, execute, associations)
    rules = apply_rules(report.measurements)
    verdict = decide(rules)
    problems += report.errors

    payload = writer.assessment_payload(parsed, mapping, verdict, rules, report.facts)
    try:
        writeup, check = await writer.explain(client, text, payload, pid)
        explained_by = "llm"
    except Exception as exc:  # keep the verdict even when the model is unavailable
        log.warning("rq explanation failed, using rule messages: %s", exc)
        writeup, check, explained_by = writer.fallback_writeup(verdict, rules), None, "rules"

    return Assessment(
        parsed=parsed,
        mapping=mapping,
        verdict=verdict,
        rules=rules,
        facts=report.facts,
        writeup=writeup,
        grounding=check,
        explained_by=explained_by,
        problems=problems,
        query_ids=sorted(set(report.measurements.query_ids.values())),
    )
