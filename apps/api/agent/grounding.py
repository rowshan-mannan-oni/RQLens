"""Check that every number in an answer appears in a tool result.

Numbers are taken from the answer text (code spans, dates and identifiers like `Q3` or
`col_2` are skipped) and matched against every number the model saw in tool results or the
question, allowing for rounding to the precision written: "12.3" matches 12.34, "45%" matches
0.4512 or 45.12, "1.2 million" matches 1,234,567, "6.6e-54" or "6.6 x 10^-54" matches
6.648e-54, and a bound such as "p < 0.001" matches any
value on the right side of it. Whole numbers from 0 to 10 are exempt
because they usually count things in the sentence ("the top 3 groups").
"""

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

EXEMPT_MAX = 10

CODE = re.compile(r"`[^`]*`")
DATE = re.compile(r"\b\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?\b")
NUMBER = re.compile(
    r"(?:(?P<op>[<>≤≥])=?\s*)?(?<![\w.])(?P<sign>-)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    # Scientific notation: 1.2e-5, 1.2E-5, 1.2 x 10^-5 (also with a multiplication sign)
    r"(?:[eE](?P<exp>[-+]?\d+)|\s?[\u00d7x*]\s?10\^?(?P<exp10>[-\u2212+]?\d+))?"
    r"(?P<pct>\s?%)?"
    r"(?:\s?(?P<scale>thousand|million|billion|[kKMB])\b)?"
    r"(?![\w.]*[A-Za-z_])"
)
ANY_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
SCALES = {"thousand": 1e3, "k": 1e3, "K": 1e3, "million": 1e6, "M": 1e6, "billion": 1e9, "B": 1e9}


@dataclass(frozen=True)
class Claim:
    text: str
    value: float
    decimals: int
    percent: bool
    scale: float
    bound: str | None = None  # "<" or ">" when the text states a bound


@dataclass(frozen=True)
class GroundingResult:
    ok: bool
    checked: int
    unsupported: list[str]

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "checked": self.checked, "unsupported": self.unsupported}


def extract_claims(text: str) -> list[Claim]:
    text = DATE.sub(" ", CODE.sub(" ", text))
    claims: list[Claim] = []
    for m in NUMBER.finditer(text):
        raw = m.group("num").replace(",", "")
        value = float(raw)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        scale = SCALES.get(m.group("scale") or "", 1.0)
        exponent = m.group("exp") or m.group("exp10")
        if exponent:
            scale *= 10.0 ** int(exponent.replace("\u2212", "-"))
        percent = m.group("pct") is not None
        exempt = not m.group("op") and decimals == 0 and value <= EXEMPT_MAX
        if exempt and not percent and scale == 1.0:
            continue
        if m.group("sign"):
            value = -value
        bound = {"<": "<", "≤": "<", ">": ">", "≥": ">"}.get(m.group("op") or "")
        claims.append(Claim(m.group(0).strip(), value, decimals, percent, scale, bound))
    return claims


def collect_numbers(*sources: Any) -> list[float]:
    """Every number inside the given JSON-like values, including numbers written in strings."""
    out: list[float] = []

    def walk(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, int | float):
            if math.isfinite(v):
                out.append(float(v))
        elif isinstance(v, str):
            out.extend(float(n) for n in ANY_NUMBER.findall(v.replace(",", "")))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x)
        else:
            walk(json.loads(json.dumps(v, default=str)))

    for s in sources:
        walk(s)
    return out


def supported(claim: Claim, pool: Iterable[float]) -> bool:
    tolerance = 0.5 * 10 ** (-claim.decimals) * claim.scale * (1 + 1e-9)
    target = claim.value * claim.scale
    if claim.bound:
        bounded = [x * 100 if claim.percent else x for x in pool]
        if claim.bound == "<":
            return any(x < target + tolerance for x in bounded)
        return any(x > target - tolerance for x in bounded)
    candidates = [target, abs(target)]
    for v in pool:
        values = (v, v * 100) if claim.percent else (v,)
        for c in values:
            if any(abs(abs(c) - abs(t)) <= tolerance for t in candidates):
                return True
    return False


def check(answer: str, pool: list[float]) -> GroundingResult:
    claims = extract_claims(answer)
    unsupported = [c.text for c in claims if not supported(c, pool)]
    return GroundingResult(not unsupported, len(claims), list(dict.fromkeys(unsupported)))
