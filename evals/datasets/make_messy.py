"""Build messy_survey/v1 from cps1985/v1: a realistic messy spreadsheet export.

Semicolon-delimited, Latin-1 encoded, headers with spaces, accents and units, the placeholder
values "N/A" and -999 for missing experience, and some blank regions. Deterministic: run it
again and the file is byte-identical.

Run: python evals/datasets/make_messy.py
"""

import csv
import random
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "cps1985" / "v1" / "cps1985.csv"
TARGET = HERE / "messy_survey" / "v1" / "messy_survey.csv"

HEADERS = {
    "rownames": "Respondent #",
    "wage": "Salaire horaire ($/h)",
    "education": "Années d'études",
    "experience": "Expérience (années)",
    "age": "Âge",
    "ethnicity": "Ethnicity",
    "region": "Région",
    "gender": "Gender",
    "occupation": "Occupation",
    "sector": "Sector",
    "union": "Union member?",
    "married": "Married",
}


def main() -> None:
    rng = random.Random(1985)
    with SOURCE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for row in rows:
        values = [row[k] for k in HEADERS]
        r = rng.random()
        if r < 0.03:
            values[3] = "-999"  # experience
        elif r < 0.05:
            values[3] = "N/A"
        if rng.random() < 0.02:
            values[6] = ""  # region
        out_rows.append(values)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open("w", encoding="latin-1", newline="") as f:
        writer = csv.writer(f, delimiter=";", lineterminator="\r\n")
        writer.writerow(HEADERS.values())
        writer.writerows(out_rows)


if __name__ == "__main__":
    main()
