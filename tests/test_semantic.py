"""Personal-data detection and masking, data dictionaries, and the column describer."""

import json
from pathlib import Path
from typing import Any

import duckdb
import httpx2
import pytest

from api.ingest.loader import load_csv
from api.llm.client import LLMClient
from api.llm.tracing import TraceRecord
from api.profiler.tables import profile_table
from api.semantic.describer import column_evidence, describe
from api.semantic.dictionary import DictionaryError, match_entries, parse_dictionary
from api.semantic.pii import detect, scrub

PEOPLE = """\
participant_id,First Name,contact,phone_no,city,comment,score,name
1,Ana,ana@example.org,+1 555-123-4567,Paris,"Call me on 555 123 4567",3,A
2,Ben,ben@example.org,+1 555-987-6543,Lyon,fine,4,B
3,Cleo,cleo@uni.edu,+44 20 7946 0958,Paris,write to cleo@uni.edu,5,C
4,Dev,dev@example.com,+1 555-222-3333,Nice,ok,4,A
"""


@pytest.fixture
def people(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "people.csv"
    path.write_text(PEOPLE, encoding="utf-8")
    con = duckdb.connect()
    result = profile_table(con, load_csv(con, path, "people"))
    return {
        r.column.name: (
            r.column,
            r.profile,
            detect(con, "people", r.column.name, r.column.physical_type, r.profile),
        )
        for r in result.columns
    }


def test_pii_detection(people: dict[str, Any]) -> None:
    flagged = {name: pii.reason for name, (_, _, pii) in people.items() if pii.is_pii}
    assert flagged == {
        "first_name": "person name (column name)",
        "contact": "email address (100% of values)",  # found by its values, not its name
        "phone_no": "phone number (column name)",
        # A bare "name" counts only when values are mostly unique (here 3 of 4).
        "name": "person name (column name, mostly unique values)",
    }
    assert not people["city"][2].is_pii and not people["score"][2].is_pii


def test_scrub() -> None:
    assert scrub("write to cleo@uni.edu") == "write to <email>"
    assert scrub("Call me on 555 123 4567") == "Call me on <phone>"
    assert "1234567890123" not in scrub("id 1234567890123")
    assert scrub("scored 4 of 5") == "scored 4 of 5"


def test_evidence_hides_personal_values(people: dict[str, Any]) -> None:
    col, profile, pii = people["contact"]
    ev = column_evidence(
        col.name, col.original_name, profile["semantic_type"], pii.is_pii, profile, True
    )
    assert ev["personal_data"] is True
    assert "frequent_values" not in ev and "sample_values" not in ev

    col, profile, pii = people["comment"]
    ev = column_evidence(
        col.name, col.original_name, profile["semantic_type"], pii.is_pii, profile, True
    )
    shown = json.dumps(ev)
    assert "cleo@uni.edu" not in shown and "555 123 4567" not in shown
    assert "<email>" in shown


def test_evidence_without_samples(people: dict[str, Any]) -> None:
    col, profile, pii = people["city"]
    ev = column_evidence(
        col.name, col.original_name, profile["semantic_type"], pii.is_pii, profile, False
    )
    assert "frequent_values" not in ev and "sample_values" not in ev
    assert ev["distinct_values"] == 3


def test_dictionary_parse_and_match() -> None:
    raw = (
        "﻿Variable;Label\n"  # Excel adds a byte-order mark
        "Age (yrs);Age in years at interview\n"
        "INCOME;Yearly income, USD\n"
        "unknown_var;x\n"
    )
    entries = parse_dictionary(raw.encode("utf-8"))
    assert [e.name for e in entries] == ["Age (yrs)", "INCOME", "unknown_var"]
    matched, unmatched = match_entries(entries, [("age_yrs", "Age (yrs)"), ("income", "Income")])
    assert matched == {"age_yrs": "Age in years at interview", "income": "Yearly income, USD"}
    assert unmatched == ["unknown_var"]


def test_dictionary_needs_known_headers() -> None:
    with pytest.raises(DictionaryError):
        parse_dictionary(b"foo,bar\n1,2\n")


async def test_describer_prompt_and_mapping(people: dict[str, Any]) -> None:
    sent: list[Any] = []

    def provider(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        sent.append(body)
        reply = {
            "columns": [
                {
                    "name": "contact",
                    "description": "Email address of the participant.",
                    "confidence": "high",
                },
                {"name": "score", "description": "Probably a 1-5 rating.", "confidence": "low"},
                {"name": "not_a_column", "description": "x", "confidence": "low"},
            ]
        }
        return httpx2.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(reply)},
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    traces: list[TraceRecord] = []

    async def tracer(record: TraceRecord) -> None:
        traces.append(record)

    client = LLMClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        max_retries=0,
        tracer=tracer,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(provider)),
    )
    evidence = [
        column_evidence(c.name, c.original_name, p["semantic_type"], pii.is_pii, p, True)
        for c, p, pii in people.values()
    ]
    found = await describe(
        client, filename="people.csv", project_topic="t", columns=evidence, project_id=1
    )

    assert set(found) == {"contact", "score"}  # unknown names are dropped
    assert found["score"].confidence == "low"
    user_message = sent[0]["messages"][1]["content"]
    assert user_message.startswith("<dataset>") and user_message.endswith("</dataset>")
    for secret in ("ana@example.org", "+1 555-123-4567", "Ana", "cleo@uni.edu"):
        assert secret not in user_message
    assert traces[0].prompt_version == "describe_columns.v1"
    assert traces[0].project_id == 1
