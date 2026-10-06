import pymupdf
import pytest

from api.papers.parser import parse_bytes
from evals.literature.synth import load_specs, render_pdf, scanned_pdf

SPECS = load_specs()


@pytest.fixture(scope="module")
def pdfs() -> dict[str, bytes]:
    return {pid: render_pdf(spec) for pid, spec in SPECS.items()}


@pytest.fixture(scope="module")
def parsed(pdfs):
    return {pid: parse_bytes(pdf) for pid, pdf in pdfs.items()}


def texts(paper) -> list[str]:
    return [p.text for p in paper.passages]


def find(paper, start: str):
    return next(p for p in paper.passages if p.text.startswith(start))


def test_metadata_from_first_page(parsed):
    for pid, spec in SPECS.items():
        meta = parsed[pid].metadata
        assert meta.title == spec.title, pid
        assert meta.authors == spec.authors, pid
        assert meta.year == spec.year, pid
        assert meta.doi == spec.doi, pid
        assert meta.venue == spec.venue, pid


def test_two_column_reading_order_and_sections(parsed):
    paper = parsed["defect-gnn"]
    kinds = [s.kind for s in paper.sections]
    assert kinds == [
        "abstract", "introduction", "related_work", "method", "experiments", "results",
        "limitations", "conclusion", "references",
    ]  # fmt: skip
    t = texts(paper)
    # The left column's last sentence comes before the right column's first one.
    rq1 = t.index(next(x for x in t if x.startswith("RQ1:")))
    rq2 = t.index(next(x for x in t if x.startswith("RQ2:")))
    tca = t.index(next(x for x in t if x.startswith("Transfer learning methods")))
    assert rq1 < rq2 < tca
    assert find(paper, "We use 18 open-source").section_kind == "experiments"


def test_hyphenation_is_undone_and_sentences_are_whole(parsed):
    paper = parsed["defect-gnn"]
    assert "\u2010" not in " ".join(t for t in texts(paper) if not t.startswith("These patterns"))
    sentence = find(paper, "We use 18 open-source Java projects")
    assert sentence.text.endswith("of which 2,931 files are labelled defective.")
    # A sentence wrapped across a block boundary is one passage.
    deep = find(paper, "Deep learning approaches")
    assert deep.text.endswith("ignore the tree structure of the code.")


def test_running_headers_and_page_numbers_removed(parsed):
    for pid, paper in parsed.items():
        assert not any(t.strip().isdigit() for t in texts(paper)), pid
        if paper.page_count < 2:
            continue  # a header on one page cannot be told apart from text
        header = (SPECS[pid].running_header or "").upper()
        assert not any(header in t.upper() for t in texts(paper)), pid


def test_abstract_inline_and_heading_styles(parsed):
    for pid in ("defect-gnn", "sleep-students"):
        first_abstract = next(p for p in parsed[pid].passages if p.section_kind == "abstract")
        assert first_abstract.text.startswith(SPECS[pid].abstract.split(".")[0]), pid
        assert not first_abstract.text.lower().startswith("abstract")


def test_captions_and_references(parsed):
    paper = parsed["defect-gnn"]
    caption = find(paper, "Table 2:")
    assert caption.kind == "caption" and caption.citable
    refs = [p for p in paper.passages if p.kind == "reference"]
    assert len(refs) == len(SPECS["defect-gnn"].references)
    assert all(not p.citable and p.section_kind == "references" for p in refs)


def test_labels_and_rectangles_point_into_the_page(parsed):
    paper = parsed["sleep-students"]
    labels = [p.label for p in paper.passages]
    assert len(set(labels)) == len(labels)
    assert labels[0] == "P1-S1"
    for p in paper.passages:
        assert p.label.startswith(f"P{p.page}-S")
        width, height = paper.page_sizes[p.page - 1]
        assert p.rects
        for x0, y0, x1, y1 in p.rects:
            assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height


def test_rectangles_cover_the_sentence_text(pdfs, parsed):
    paper = parsed["sleep-students"]
    target = find(paper, "Compared with students who slept seven to eight hours")
    doc = pymupdf.open(stream=pdfs["sleep-students"], filetype="pdf")
    page = doc[target.page - 1]
    words = " ".join(page.get_textbox(pymupdf.Rect(r)) for r in target.rects)
    assert "0.31 points lower" in " ".join(words.split()).replace("\u2010", "")


def test_scanned_pdf_needs_ocr(pdfs):
    result = parse_bytes(scanned_pdf(pdfs["no-limitations"]))
    assert result.needs_ocr
    assert result.passages == []
    assert result.page_count == 1


def test_numbers_and_abbreviations_do_not_split_sentences(parsed):
    paper = parsed["defect-gnn"]
    assert find(paper, "The improvement is statistically significant").text.endswith(
        "(Cliff's delta = 0.48)."
    )


def test_scanned_pdf_read_with_ocr(pdfs):
    pytest.importorskip("rapidocr_onnxruntime")
    pytest.importorskip("wordninja")
    spec = SPECS["no-limitations"]
    result = parse_bytes(scanned_pdf(pdfs["no-limitations"], dpi=300), ocr=True)
    assert not result.needs_ocr
    assert result.ocr_pages == [1]
    assert result.metadata.title == spec.title
    assert result.metadata.authors == spec.authors
    assert [s.kind for s in result.sections] == [
        "abstract", "introduction", "method", "results", "conclusion", "references",
    ]  # fmt: skip
    method = find(result, "We conducted semi-structured interviews")
    assert method.section_kind == "method"
    assert method.text.endswith("in Central Europe.")
    width, height = result.page_sizes[0]
    for x0, y0, x1, y1 in method.rects:
        assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height


def test_unglue_restores_spaces():
    pytest.importorskip("wordninja")
    from api.papers.ocr import unglue

    assert unglue("Reviewersreportedspendinglesstime on test code.We agree") == (
        "Reviewers reported spending less time on test code. We agree"
    )
    assert unglue("GraphDP uses e.g. ASTs") == "GraphDP uses e.g. ASTs"
