from evals import lit_eval

LABELS = lit_eval.load_labels()


def test_labels_cover_every_paper_and_column():
    columns = {c.key for c in lit_eval.TEMPLATE.columns}
    for paper_id, _ in lit_eval.corpus():
        assert set(LABELS[paper_id]) == columns, paper_id


def test_value_rubric():
    label = {"key_terms": ["89.4", "accuracy|acc"], "forbidden": ["91.2"]}
    assert lit_eval.value_correct(label, "Top-1 accuracy of 89.4%")
    assert not lit_eval.value_correct(label, "Top-1 accuracy of 91.2% (89.4% after fixing)")
    assert not lit_eval.value_correct(label, "89.4%")
    assert lit_eval.value_correct({"value": ["A B", "C D"]}, ["a b", "c  d"])
    assert lit_eval.value_correct({"value": 2023}, 2023.0)


async def test_oracle_scores_full_marks_on_planted_papers():
    """The oracle answers from the labels: anything below 100% is a parser or harness bug."""
    client = lit_eval.LitOracle(LABELS)
    for paper_id, spec in lit_eval.corpus(["no-limitations", "abstract-disagree"]):
        r = await lit_eval.run_paper(
            client, paper_id, spec, LABELS[paper_id], check=True, retrieval=False
        )
        for c in r["cells"]:
            assert c.get("correct", c.get("not_found_correct")), c
            if "recall" in c:
                assert c["recall"] == 1.0 and c["citation_hits"] == c["citations_n"], c
