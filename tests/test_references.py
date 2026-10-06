from types import SimpleNamespace

from api.papers.references import latex_to_text, match, parse_bibtex, parse_ris

BIB = r"""
% Exported by Zotero
@article{okafor2023graph,
  title = {Graph Neural Networks for {Cross-Project} Defect Prediction},
  author = {Okafor, Maria and Brandt, Daniel and Zhang, Wei},
  journal = {IEEE Transactions on Software Engineering},
  year = {2023},
  volume = 49,
  doi = {10.1109/TSE.2023.3271190},
  file = {Full Text PDF:files/12/Okafor - 2023 - Graph.pdf:application/pdf}
}
@inproceedings{m{\"u}ller2021,
  title = "Code Review at {M}{\"u}nchen: an {\'E}tude",
  author = {M{\"u}ller, J{\"o}rg and others},
  booktitle = {Proceedings of ICSE},
  date = {2021-05-03},
}
@comment{ignored}
"""

RIS = """TY  - JOUR
AU  - Okonkwo, Chidi
AU  - Lindqvist, Astrid
TI  - Sleep Duration and Academic Performance in First-Year University Students
T2  - Journal of Adolescent Health Research
PY  - 2021///
DO  - https://doi.org/10.1016/j.jahr.2021.04.012
L1  - file:///C:/Users/me/Zotero/storage/AB12/sleep.pdf
ER  -
TY  - CONF
TI  - How Developers Review Test Code
PY  - 2022
ER  -
"""


def test_bibtex():
    a, b = parse_bibtex(BIB)
    assert a.key == "okafor2023graph" and a.kind == "article"
    assert a.title == "Graph Neural Networks for Cross-Project Defect Prediction"
    assert a.authors == ["Maria Okafor", "Daniel Brandt", "Wei Zhang"]
    assert a.year == 2023 and a.venue == "IEEE Transactions on Software Engineering"
    assert a.doi == "10.1109/tse.2023.3271190"
    assert a.files == ["Okafor - 2023 - Graph.pdf"]
    assert b.title == "Code Review at M\u00fcnchen: an \u00c9tude"
    assert b.authors == ["J\u00f6rg M\u00fcller"]
    assert b.year == 2021 and b.venue == "Proceedings of ICSE"


def test_ris():
    a, b = parse_ris(RIS)
    assert a.authors == ["Chidi Okonkwo", "Astrid Lindqvist"]
    assert a.year == 2021 and a.doi == "10.1016/j.jahr.2021.04.012"
    assert a.venue == "Journal of Adolescent Health Research"
    assert a.files == ["sleep.pdf"]
    assert b.kind == "CONF" and b.title == "How Developers Review Test Code" and b.key == "ris2"


def test_latex():
    assert (
        latex_to_text(r"Gr{\"o}{\ss}e \& {\'e}t\'e --- x")
        == "Gr\u00f6\u00dfe & \u00e9t\u00e9 \u2014 x"
    )
    assert latex_to_text(r"Pe\~{n}a, 1--2") == "Pe\u00f1a, 1\u20132"


def test_match_by_doi_then_title():
    papers = [
        SimpleNamespace(
            id=1, doi=None, title="Graph neural networks for cross-project defect prediction."
        ),
        SimpleNamespace(id=2, doi="10.1016/j.jahr.2021.04.012", title=None),
        SimpleNamespace(id=3, doi=None, title="Something else entirely about code"),
    ]
    a, _ = parse_bibtex(BIB)
    s, conf = parse_ris(RIS)
    assert match(a, papers).id == 1  # title, ignoring case and punctuation
    assert match(s, papers).id == 2  # DOI
    assert match(conf, papers) is None
