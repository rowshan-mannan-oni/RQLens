"""A sample project with a public dataset, for trying the app and for demos.

Palmer penguins (Horst, Hill and Gorman 2020, CC0): 344 penguins from three species on three
islands, with body measurements and some missing values. The research questions come with a
ready-made parse and mapping, so they are assessed even without an AI key.
"""

from pathlib import Path
from typing import Any

SAMPLE_CSV = Path(__file__).parent / "penguins.csv"
TITLE = "Sample: Palmer penguins"
TOPIC = (
    "Body size and sex differences among three penguin species in the Palmer Archipelago, "
    "Antarctica (sample project with a public dataset)."
)


def _construct(name: str, role: str, column: str | None) -> dict[str, Any]:
    candidates = (
        []
        if column is None
        else [
            {
                "table": "penguins",
                "column": column,
                "expression": None,
                "match": "direct",
                "kind": None,
                "justification": "Sample mapping.",
            }
        ]
    )
    return {"name": name, "role": role, "candidates": candidates, "status": "proposed"}


def _mapping(*constructs: dict[str, Any], population: str | None = None) -> dict[str, Any]:
    return {
        "constructs": list(constructs),
        "population_filter": population,
        "time_column": None,
        "time_start": None,
        "time_end": None,
        "notes": "",
    }


QUESTIONS: list[dict[str, Any]] = [
    {
        "text": "Do Gentoo penguins have a higher body mass than Adelie penguins?",
        "parsed": {
            "type": "comparative",
            "population": "Adelie and Gentoo penguins",
            "constructs": [
                {"name": "body mass", "role": "dependent", "description": ""},
                {"name": "species", "role": "independent", "description": ""},
            ],
            "comparison": "Gentoo versus Adelie",
            "time_scope": None,
        },
        "mapping": _mapping(
            _construct("body mass", "dependent", "body_mass_g"),
            _construct("species", "independent", "species"),
            population="species IN ('Adelie', 'Gentoo')",
        ),
    },
    {
        "text": "Is flipper length associated with body mass across all penguins?",
        "parsed": {
            "type": "correlational",
            "population": "all penguins",
            "constructs": [
                {"name": "body mass", "role": "dependent", "description": ""},
                {"name": "flipper length", "role": "independent", "description": ""},
            ],
            "comparison": None,
            "time_scope": None,
        },
        "mapping": _mapping(
            _construct("body mass", "dependent", "body_mass_g"),
            _construct("flipper length", "independent", "flipper_length_mm"),
        ),
    },
    {
        "text": "Does diet affect how quickly penguin chicks grow?",
        "parsed": {
            "type": "causal",
            "population": "penguin chicks",
            "constructs": [
                {"name": "chick growth rate", "role": "dependent", "description": ""},
                {"name": "diet", "role": "independent", "description": ""},
            ],
            "comparison": None,
            "time_scope": None,
        },
        "mapping": _mapping(
            _construct("chick growth rate", "dependent", None),
            _construct("diet", "independent", None),
        ),
    },
]
