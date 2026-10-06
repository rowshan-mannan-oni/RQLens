"""Benchmark D: literature-table extraction with citations, against hand labels.

Each paper in literature/papers.v1.json is rendered to a PDF, read by the app's parser and
filled with the built-in literature review template, exactly as in the app. Every
(paper, column) has a label in literature/labels.v1.jsonl:

- `found`: whether the paper states it. `optional` labels are left out of the not-found score
  (the paper is ambiguous, for example an aim that may or may not count as a research question).
- `key_terms`: what a correct value must contain; `a|b` means either. `forbidden`: what it must
  not contain (the planted abstract-versus-results case).
- `support`: groups of sentences that support the value. Each group is one piece of evidence;
  its items are equivalent alternatives (the same fact in the abstract and in the results).
- `value`: exact value for metadata columns (title, authors, year).

Metrics:
- cell accuracy: found cells whose value passes the rubric (key terms, forbidden terms, or the
  exact value for metadata). A rubric, not an LLM judge: it is strict on facts, lenient on
  wording.
- citation precision: cited passages that contain a labelled supporting sentence.
- citation recall: share of a cell's evidence groups covered by its citations.
- not-found accuracy: cells the paper lacks that are answered "not found".
- unverified rate, and cost and time per paper.

Experiments (plan section 6, benchmark D): `--retrieval` sends retrieved passages per column
instead of the whole paper (7), `--no-check` turns off the citation check and retry (8),
`--model` compares models (9).
"""

import hashlib
import json
import re
import time
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from api.llm.client import LLMResult
from api.papers.parser import parse_bytes
from api.review import extract as extract_mod
from api.review.citations import normalise
from api.review.extract import ExtractionOut, PaperInput, extract
from api.review.templates import BUILTIN
from evals.literature.synth import load_specs, render_pdf

EVALS = Path(__file__).parent
LABELS = EVALS / "literature" / "labels.v1.jsonl"
REAL_PDFS = EVALS / "literature" / "pdfs"  # real papers: <paper id>.pdf, labelled like the rest
CACHE = EVALS / ".cache" / "literature"
TEMPLATE = BUILTIN["builtin:literature_review"]


def load_labels() -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for line in LABELS.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            out.setdefault(d["paper"], {})[d["column"]] = d
    return out


def paper_pdf(paper_id: str, spec: Any) -> bytes:
    """Render a paper once; cached by the hash of its spec."""
    key = hashlib.sha256(json.dumps(spec.__dict__, default=lambda o: o.__dict__).encode())
    path = CACHE / f"{paper_id}-{key.hexdigest()[:12]}.pdf"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(render_pdf(spec))
    return path.read_bytes()


def paper_input(pdf: bytes) -> PaperInput:
    parsed = parse_bytes(pdf)
    passages = [
        SimpleNamespace(
            id=p.ordinal + 1,
            ordinal=p.ordinal,
            label=p.label,
            page=p.page,
            text=p.text,
            kind=p.kind,
            section_kind=p.section_kind,
            section=p.section,
        )
        for p in parsed.passages
    ]
    m = parsed.metadata
    return PaperInput(passages, m.title, m.authors or None, m.year, m.venue, m.doi)


# --- scoring -----------------------------------------------------------------------------------


def value_text(value: Any) -> str:
    if isinstance(value, list):
        return " ; ".join(str(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


def _has(text: str, term: str) -> bool:
    return any(normalise(alt) in text for alt in term.split("|"))


def value_correct(label: dict[str, Any], value: Any) -> bool:
    if "value" in label:
        want = label["value"]
        if isinstance(want, list):
            return [normalise(str(v)) for v in value or []] == [normalise(w) for w in want]
        if isinstance(want, int | float):
            return value is not None and float(value) == float(want)
        return normalise(value_text(value)) == normalise(str(want))
    text = normalise(value_text(value))
    ok = all(_has(text, t) for t in label.get("key_terms", []))
    return ok and not any(_has(text, t) for t in label.get("forbidden", []))


def _supports(passage_text: str, label: dict[str, Any]) -> list[int]:
    """Indexes of the evidence groups this passage supports."""
    t = normalise(passage_text)
    return [
        i
        for i, group in enumerate(label.get("support", []))
        if any(normalise(alt) in t for alt in group)
    ]


def score_cell(label: dict[str, Any], cell: Any, passages: dict[int, Any]) -> dict[str, Any]:
    status = cell.status
    found_pred = status not in ("not_found", "failed")
    out: dict[str, Any] = {
        "paper": label["paper"],
        "column": label["column"],
        "label_found": label["found"],
        "optional": bool(label.get("optional")),
        "status": status,
        "value": cell.value,
        "note": cell.note,
        "citations": [
            {"label": c.get("label"), "quote": c.get("quote"), "verified": c.get("verified")}
            for c in cell.citations
        ],
    }
    if not label["found"]:
        out["not_found_correct"] = status == "not_found"
        return out
    out["correct"] = found_pred and value_correct(label, cell.value)
    if label.get("support") and found_pred:
        cited = [passages.get(c.get("passage_id")) for c in cell.citations]
        hits = [_supports(p.text, label) if p is not None else [] for p in cited]
        out["citation_hits"] = sum(1 for h in hits if h)
        out["citations_n"] = len(cited)
        covered = {i for h in hits for i in h}
        out["recall"] = len(covered) / len(label["support"])
    return out


def summarise(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    cells = [c for r in results for c in r["cells"]]

    def per_paper(key: str) -> float:
        return sum(r[key] for r in results) / max(1, len(results))

    def pct(n: int, d: int) -> str:
        return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"

    found = [c for c in cells if c["label_found"] and not (c["optional"] and not c.get("correct"))]
    correct = sum(1 for c in found if c.get("correct"))
    cited = [c for c in cells if "citations_n" in c]
    hits = sum(c["citation_hits"] for c in cited)
    n_cit = sum(c["citations_n"] for c in cited)
    recall = [c["recall"] for c in cited]
    absent = [c for c in cells if not c["label_found"] and not c["optional"]]
    nf = sum(1 for c in absent if c["not_found_correct"])
    answered = [c for c in cells if c["status"] not in ("not_found", "failed")]
    unverified = sum(1 for c in answered if c["status"] == "unverified")
    missed = [c for c in found if c["status"] == "not_found"]
    lines = [
        f"# Benchmark D: literature extraction ({meta['started']})",
        "",
        f"Model: {meta['model']} · check: {meta['check']} · passages: {meta['passages']} · "
        f"git {meta['git_sha']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cell accuracy | {pct(correct, len(found))} |",
        f"| Citation precision | {pct(hits, n_cit)} |",
        "| Citation recall | "
        + (f"{100 * sum(recall) / len(recall):.0f}% over {len(recall)} cells" if recall else "n/a")
        + " |",
        f"| Not-found accuracy | {pct(nf, len(absent))} |",
        f"| Said not found when the paper has it | {pct(len(missed), len(found))} |",
        f"| Unverified rate | {pct(unverified, len(answered))} |",
        f"| Papers | {len(results)} |",
        f"| Time per paper | {per_paper('seconds'):.1f} s |",
        f"| Cost per paper | ${per_paper('cost_usd'):.4f} |",
        f"| LLM calls per paper | {per_paper('llm_calls'):.1f} |",
        "",
        "## Planted cases",
        "",
    ]
    for r in results:
        for c in r["cells"]:
            if (c["paper"], c["column"]) == ("no-limitations", "limitations"):
                lines.append(f"- No limitations section → not found: **{c['not_found_correct']}**")
            if (c["paper"], c["column"]) == ("abstract-disagree", "results"):
                lines.append(
                    f"- Abstract and results disagree → corrected value and results "
                    f"citation: **{bool(c.get('correct')) and c.get('citation_hits', 0) > 0}**"
                )
    wrong = [c for c in cells if c.get("correct") is False or c.get("not_found_correct") is False]
    if wrong:
        lines += ["", "## Errors", "", "| Paper | Column | Status | Value |", "|---|---|---|---|"]
        for c in wrong:
            v = value_text(c["value"]).replace("|", "/")[:100]
            lines.append(f"| {c['paper']} | {c['column']} | {c['status']} | {v} |")
    return "\n".join(lines) + "\n"


# --- the oracle ------------------------------------------------------------------------------


class LitOracle:
    """Answers from the labels, quoting the labelled sentences. A harness self-test: an oracle
    run should score 100% on every metric; anything less is a harness or parser bug."""

    model = "oracle"
    embedding_model = ""

    def __init__(self, labels: dict[str, dict[str, dict[str, Any]]]) -> None:
        self.labels = labels
        self.paper = ""

    async def complete_structured(
        self, messages: Sequence[dict[str, str]], schema: type, **kwargs: Any
    ) -> LLMResult[Any]:
        first = next(
            m["content"] for m in messages if m["role"] == "user" and "<columns>" in m["content"]
        )
        columns = json.loads(re.search(r"<columns>\n(.*?)\n</columns>", first, re.S).group(1))  # type: ignore[union-attr]
        passages = re.findall(r"^\[(P\d+-S\d+)\] \(\w+\) (.*)$", first, re.M)
        cells = []
        for col in columns:
            label = self.labels[self.paper].get(col["key"])
            if label is None or not label["found"]:
                cells.append({"column": col["key"], "found": False, "reason": "Not stated."})
                continue
            terms = [t.split("|")[0] for t in label.get("key_terms", [])]
            value: Any = terms if col["kind"] == "list" else "; ".join(terms)
            citations = []
            for group in label.get("support", []):
                for alt in group:
                    hit = next((p for p in passages if normalise(alt) in normalise(p[1])), None)
                    if hit:
                        start = hit[1].lower().find(alt.lower())
                        quote = hit[1][start : start + len(alt)] if start >= 0 else alt
                        citations.append({"passage": hit[0], "quote": quote})
                        break
            cells.append({"column": col["key"], "found": True, "value": value,
                          "citations": citations, "confidence": "high"})  # fmt: skip
        parsed = ExtractionOut.model_validate({"cells": cells})
        return LLMResult(
            text=parsed.model_dump_json(),
            parsed=parsed,
            model="oracle",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal(0),
            latency_ms=0,
        )


async def run_paper(
    client: Any,
    paper_id: str,
    spec: Any,
    labels: dict[str, dict[str, Any]],
    *,
    check: bool,
    retrieval: bool,
) -> dict[str, Any]:
    if spec is None:
        pdf = (REAL_PDFS / f"{paper_id}.pdf").read_bytes()
    else:
        pdf = paper_pdf(paper_id, spec)
    paper = paper_input(pdf)
    if isinstance(client, LitOracle):
        client.paper = paper_id
    saved = extract_mod.LONG_PAPER_CHARS
    if retrieval:
        extract_mod.LONG_PAPER_CHARS = 0  # always send retrieved passages per column
    t0 = time.perf_counter()
    try:
        out = await extract(client, TEMPLATE.columns, paper, check=check)
    finally:
        extract_mod.LONG_PAPER_CHARS = saved
    seconds = time.perf_counter() - t0
    by_id = {p.id: p for p in paper.passages}
    cells = {c.column_key: c for c in out.cells}
    scored = [score_cell(lab, cells[col], by_id) for col, lab in labels.items() if col in cells]
    return {
        "paper": paper_id,
        "seconds": round(seconds, 2),
        "llm_calls": out.llm_calls,
        "input_tokens": out.input_tokens,
        "output_tokens": out.output_tokens,
        "cost_usd": out.cost_usd,
        "passages_sent": out.passages_sent,
        "passages": len(paper.passages),
        "retried": out.retried,
        "cells": scored,
    }


def corpus(ids: list[str] | None = None) -> list[tuple[str, Any]]:
    """Synthetic papers (with their spec) and real PDFs in literature/pdfs/ (spec None)."""
    papers: list[tuple[str, Any]] = list(load_specs().items())
    if REAL_PDFS.is_dir():
        papers += [(p.stem, None) for p in sorted(REAL_PDFS.glob("*.pdf"))]
    return [(k, v) for k, v in papers if not ids or k in ids]
