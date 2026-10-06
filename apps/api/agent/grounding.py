"""Grounding check: every number in an answer must come from a tool result.

Numbers are extracted from the answer text and matched against all numbers seen in tool results
during the turn, allowing for rounding to the precision written. Percentages may match a share
(0.42 -> 42%). Numbers in the user's question and constants in executed SQL are also accepted,
because restating them is not a claim about the data. Small whole numbers (0 to 10) are exempt:
they are almost always counts of things in the answer itself ("the top 3 groups").
"""

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

EXEMPT_MAX = 10
SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "billion": 1e9, "bn": 1e9}
APPROX = re.compile(r"(about|around|roughly|approximately|nearly|almost|~|≈)\s*$", re.IGNORECASE)

# ISO dates and times are checked as whole strings, not as separate numbers.
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?\b")
CODE = re.compile(r"`[^`]*`")
NUMBER = re.compile(
    r"(?<![\w.])(?<![A-Za-z]-)"  # not part of an identifier such as q1, v2.0 or COVID-19
    r"(?P<op>[<>≤≥]=?\s*)?"
    r"(?P<sign>[-\u2212])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<exp>[eE][-+]?\d+)?"
    r"(?P<unit>\s?%|\s(?:thousand|million|billion)\b|(?:k|bn)\b)?"
    r"(?![\w])",
    re.IGNORECASE,
)


@dataclass
class Claim:
    text: str
    value: float
    decimals: int
    percent: bool
    approximate: bool
    inequality: str | None
    supported: bool = False


@dataclass
class GroundingResult:
    claims: list[Claim] = field(default_factory=list)
    unsupported_dates: list[str] = field(default_factory=list)

    @property
    def unsupported(self) -> list[str]:
        return [c.text for c in self.claims if not c.supported] + self.unsupported_dates

    @property
    def grounded(self) -> bool:
        return not self.unsupported

    def summary(self) -> dict[str, Any]:
        checked = len(self.claims) + len(self.unsupported_dates)
        return {
            "grounded": self.grounded,
            "numbers_checked": checked,
            "unsupported": self.unsupported,
        }


def extract_claims(text: str) -> tuple[list[Claim], list[str]]:
    """Numbers stated in `text`, and ISO dates stated in it."""
    text = CODE.sub(" ", text)
    dates = DATE.findall(text)
    text = DATE.sub(" ", text)
    claims = []
    for m in NUMBER.finditer(text):
        raw = m.group("num").replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        value = float(raw + (m.group("exp") or ""))
        if m.group("exp"):
            # 1.2e-5: precision follows the mantissa.
            decimals = decimals - int(m.group("exp")[1:])
        unit = (m.group("unit") or "").strip().lower()
        percent = unit == "%"
        if unit in SCALES:
            value *= SCALES[unit]
            decimals -= round(math.log10(SCALES[unit]))
        if m.group("sign"):
            value = -value
        op = (m.group("op") or "").strip() or None
        approximate = bool(APPROX.search(text[: m.start()]))
        claims.append(Claim(m.group(0).strip(), value, decimals, percent, approximate, op))
    return claims, dates


def collect_numbers(value: Any, out: set[float] | None = None) -> set[float]:
    """All finite numbers in a JSON-like value, including numbers written inside strings."""
    out = set() if out is None else out
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, int | float):
        if math.isfinite(value):
            out.add(float(value))
    elif isinstance(value, str):
        for claim in extract_claims(value)[0]:
            out.add(claim.value)
    elif isinstance(value, dict):
        for v in value.values():
            collect_numbers(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            collect_numbers(v, out)
    return out


def collect_strings(value: Any, out: list[str] | None = None) -> list[str]:
    out = [] if out is None else out
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            collect_strings(v, out)
    elif isinstance(value, list | tuple):
        for v in value:
            collect_strings(v, out)
    return out


def _matches(claim: Claim, source: float) -> bool:
    candidates = [source, -source]
    if claim.percent:
        candidates += [source * 100, -source * 100]
    if claim.inequality:
        op = claim.inequality.replace("≤", "<=").replace("≥", ">=")
        checks = {
            "<": lambda s: s < claim.value,
            "<=": lambda s: s <= claim.value,
            ">": lambda s: s > claim.value,
            ">=": lambda s: s >= claim.value,
        }
        return any(checks[op](c) for c in candidates)

    tolerance = 0.5 * 10.0 ** (-claim.decimals)
    if claim.approximate and claim.decimals == 0:
        # "about 1,200" may round 1,187 to the last non-zero digit written.
        digits = str(abs(int(claim.value)))
        trailing = len(digits) - len(digits.rstrip("0"))
        tolerance = max(tolerance, 0.5 * 10.0**trailing)
    tolerance *= 1 + 1e-9
    return any(abs(c - claim.value) <= tolerance for c in candidates)


def check(
    answer: str,
    tool_results: Iterable[Any],
    *,
    question: str = "",
    sql: Iterable[str] = (),
) -> GroundingResult:
    """Check every number in `answer` against tool results, the question and executed SQL."""
    claims, dates = extract_claims(answer)
    results = list(tool_results)
    sources = collect_numbers(results)
    sql_list = list(sql)
    for text in (question, *sql_list):
        sources |= {c.value for c in extract_claims(text)[0]}

    for claim in claims:
        if claim.inequality is None and claim.decimals <= 0 and 0 <= claim.value <= EXEMPT_MAX:
            claim.supported = True
            continue
        claim.supported = any(_matches(claim, s) for s in sources)

    haystack = "\n".join([question, *sql_list, *collect_strings(results)])
    unsupported_dates = [d for d in dates if d not in haystack and d[:10] not in haystack]
    return GroundingResult(claims, unsupported_dates)
