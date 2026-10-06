"""Review templates: the columns of a literature table.

Built-in templates live here; users make their own (stored in `review_templates`). A review
table copies its template's columns when it is created, so editing a template later does not
change existing tables.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ColumnKind = Literal["text", "list", "number", "category"]
MetadataField = Literal["title", "authors", "year", "venue", "doi"]


class TemplateColumn(BaseModel):
    key: str = Field(default="", max_length=64)
    label: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=2000)
    kind: ColumnKind = "text"
    options: list[str] = Field(default_factory=list, max_length=30)  # for kind "category"
    required: bool = False
    # Filled from the paper's parsed metadata when available, without the AI.
    metadata: MetadataField | None = None

    @field_validator("options")
    @classmethod
    def _clean_options(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(o.strip()[:120] for o in v if o.strip()))

    @model_validator(mode="after")
    def _check(self) -> "TemplateColumn":
        self.label = self.label.strip()
        if not self.key:
            self.key = slug(self.label)
        if self.kind == "category" and len(self.options) < 2:
            raise ValueError(f"Column '{self.label}' needs at least two options")
        if self.kind != "category":
            self.options = []
        return self


class Template(BaseModel):
    key: str  # builtin:<name> or user:<id>
    name: str
    description: str
    columns: list[TemplateColumn]
    builtin: bool
    version: int = 1


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return (s or "column")[:64]


def unique_keys(columns: list[TemplateColumn]) -> list[TemplateColumn]:
    """Make column keys unique (`metrics`, `metrics_2`, ...)."""
    seen: set[str] = set()
    out = []
    for c in columns:
        key, n = c.key or slug(c.label), 2
        base = key
        while key in seen:
            key = f"{base[:60]}_{n}"
            n += 1
        seen.add(key)
        out.append(c.model_copy(update={"key": key}))
    return out


def _col(label: str, instructions: str, **kw: object) -> TemplateColumn:
    return TemplateColumn(label=label, instructions=instructions, **kw)


LITERATURE_REVIEW = Template(
    key="builtin:literature_review",
    name="Literature review",
    description="The standard fields of a literature review table.",
    builtin=True,
    columns=[
        _col("Paper title", "The full title of the paper.", metadata="title", required=True),
        _col("Authors", "All authors, in the order given.", kind="list", metadata="authors"),
        _col("Year", "Year of publication.", kind="number", metadata="year"),
        _col(
            "Problem statement",
            "The problem or gap the paper addresses, in one or two sentences.",
            required=True,
        ),
        _col(
            "Research questions",
            "The research questions or hypotheses, as stated. Not found if the paper states none.",
            kind="list",
        ),
        _col(
            "Approach / method",
            "What the authors did: the method, model, study design or intervention.",
            key="approach",
            required=True,
        ),
        _col(
            "Dataset(s)",
            "The data used: names of datasets or benchmarks, or the participants or sample, "
            "with sizes if stated.",
            key="datasets",
            kind="list",
        ),
        _col(
            "Metrics",
            "The evaluation measures reported, such as accuracy or F1, with their values if "
            "stated.",
            kind="list",
        ),
        _col("Results", "The main quantitative or qualitative results, with numbers as stated."),
        _col(
            "Key findings", "The main conclusions the authors draw from the results.", kind="list"
        ),
        _col(
            "Limitations",
            "Limitations or threats to validity the authors acknowledge. Not found if the paper "
            "does not discuss any; do not invent limitations.",
            kind="list",
        ),
        _col("Conclusion", "The paper's overall conclusion in one or two sentences."),
        _col(
            "Future work",
            "Future work the authors propose. Not found if none is mentioned.",
            kind="list",
        ),
    ],
)

EMPIRICAL_SE = Template(
    key="builtin:empirical_se",
    name="Empirical software engineering",
    description="Study type, subjects and validity, for empirical software engineering papers.",
    builtin=True,
    columns=[
        _col("Paper title", "The full title of the paper.", metadata="title", required=True),
        _col("Year", "Year of publication.", kind="number", metadata="year"),
        _col(
            "Study type",
            "The research method of the study.",
            kind="category",
            options=[
                "Controlled experiment",
                "Case study",
                "Survey",
                "Interview study",
                "Mining software repositories",
                "Benchmark evaluation",
                "Mixed methods",
                "Other",
            ],
            required=True,
        ),
        _col("Research questions", "The research questions as stated.", kind="list"),
        _col(
            "Subjects",
            "The projects, systems or participants studied, with counts if stated.",
            kind="list",
        ),
        _col("Programming languages", "The programming languages studied.", kind="list"),
        _col("Metrics", "Evaluation measures and their values.", kind="list"),
        _col("Key findings", "The main findings.", kind="list"),
        _col("Threats to validity", "Threats to validity discussed by the authors.", kind="list"),
        _col(
            "Replication package",
            "Whether data or code are publicly available, with the link if given.",
        ),
    ],
)

CLINICAL_PICO = Template(
    key="builtin:clinical_pico",
    name="Clinical study (PICO)",
    description="Population, intervention, comparison and outcome, for clinical and health "
    "studies.",
    builtin=True,
    columns=[
        _col("Paper title", "The full title of the paper.", metadata="title", required=True),
        _col("Year", "Year of publication.", kind="number", metadata="year"),
        _col(
            "Study design",
            "The design of the study.",
            kind="category",
            options=[
                "Randomised controlled trial",
                "Cohort study",
                "Case-control study",
                "Cross-sectional study",
                "Systematic review",
                "Qualitative study",
                "Other",
            ],
            required=True,
        ),
        _col("Population", "Who was studied: setting, inclusion criteria and sample size."),
        _col("Sample size", "The number of participants analysed.", kind="number"),
        _col("Intervention or exposure", "The intervention, treatment or exposure studied."),
        _col("Comparison", "The control or comparison group. Not found if there is none."),
        _col("Outcomes", "The outcomes measured, with effect sizes if stated.", kind="list"),
        _col("Main result", "The main result with its effect estimate and confidence interval."),
        _col("Limitations", "Limitations stated by the authors.", kind="list"),
    ],
)

SCREENING = Template(
    key="builtin:screening",
    name="Systematic review screening",
    description="Fields for screening papers against inclusion criteria (PRISMA-style).",
    builtin=True,
    columns=[
        _col("Paper title", "The full title of the paper.", metadata="title", required=True),
        _col("Year", "Year of publication.", kind="number", metadata="year"),
        _col(
            "Publication type",
            "The kind of publication.",
            kind="category",
            options=["Primary study", "Review", "Position paper", "Tool or demo paper", "Other"],
        ),
        _col(
            "Empirical evaluation",
            "Whether the paper reports an empirical evaluation.",
            kind="category",
            options=["Yes", "No"],
        ),
        _col("Population or domain", "The population, domain or context studied."),
        _col("Main contribution", "The paper's main contribution in one sentence."),
    ],
)

BUILTIN: dict[str, Template] = {
    t.key: t for t in (LITERATURE_REVIEW, EMPIRICAL_SE, CLINICAL_PICO, SCREENING)
}
DEFAULT_TEMPLATE = LITERATURE_REVIEW.key
