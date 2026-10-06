"""Correct for multiple tests, label effect sizes, and rank results. See DECISIONS.md.

Rank is not by p-value: score = 0.4 * relevance + 0.4 * effect + 0.2 * support, halved when the
adjusted p-value is 0.05 or more. Relevance is 1 for analyses of a research question, 0.6 when a
column is mapped to some research question, 0.5 for the LLM's ideas and 0.3 for profile pairs.
Effect is the absolute effect size on a 0-to-1 scale (the square root of epsilon squared, so it
is comparable with the correlation-like measures). Support grows with log10(n), reaching 1 at
1,000 rows.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from api.insights.runner import Outcome
from api.stats.corrections import benjamini_hochberg

ALPHA = 0.05
WEIGHTS = (0.4, 0.4, 0.2)  # relevance, effect, support
NOT_SIGNIFICANT_FACTOR = 0.5
RELEVANCE = {"rq": 1.0, "mapped": 0.6, "llm": 0.5, "profile": 0.3}

# Cohen-style cut-offs for small, medium and large
CUTS = {
    "rho": (0.1, 0.3, 0.5),
    "tau": (0.1, 0.3, 0.5),
    "rank_biserial": (0.1, 0.3, 0.5),
    "cramers_v": (0.1, 0.3, 0.5),
    "epsilon_squared": (0.01, 0.06, 0.14),
}


@dataclass
class Ranked:
    outcome: Outcome
    p_adjusted: float
    effect: float  # 0 to 1
    magnitude: str  # negligible | small | medium | large
    relevance: float
    support: float
    score: float
    status: str  # finding | weak | no_evidence


def magnitude(name: str, value: float) -> str:
    small, medium, large = CUTS.get(name, (0.1, 0.3, 0.5))
    v = abs(value)
    if v >= large:
        return "large"
    if v >= medium:
        return "medium"
    if v >= small:
        return "small"
    return "negligible"


def effect_scale(name: str, value: float) -> float:
    v = abs(value)
    return min(1.0, math.sqrt(v) if name == "epsilon_squared" else v)


def support(n: int) -> float:
    return min(1.0, math.log10(n) / 3) if n > 1 else 0.0


def rank(outcomes: Sequence[Outcome], mapped_columns: set[tuple[str, str]]) -> list[Ranked]:
    """Rank successful outcomes; mapped_columns holds (table, column) pairs used by any RQ."""
    done = [o for o in outcomes if o.result is not None]
    adjusted = benjamini_hochberg([o.result.p_value for o in done if o.result])
    ranked = []
    for o, p_adj in zip(done, adjusted, strict=True):
        r = o.result
        assert r is not None
        source: str = o.spec.source
        used = {(o.spec.table, o.spec.x), (o.spec.table, o.spec.y)}
        if source != "rq" and used & mapped_columns:
            source = "mapped"
        relevance = RELEVANCE[source]
        effect = effect_scale(r.effect_size_name, r.effect_size)
        sup = support(r.n)
        w_rel, w_eff, w_sup = WEIGHTS
        score = w_rel * relevance + w_eff * effect + w_sup * sup
        size = magnitude(r.effect_size_name, r.effect_size)
        if p_adj >= ALPHA:
            score *= NOT_SIGNIFICANT_FACTOR
            status = "no_evidence"
        else:
            status = "weak" if size == "negligible" else "finding"
        ranked.append(Ranked(o, p_adj, effect, size, relevance, sup, round(score, 4), status))
    ranked.sort(key=lambda x: -x.score)
    return ranked
