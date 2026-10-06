"""Execution-match scoring for the chat benchmark (plan.md, Phase 5, benchmark A).

Two results match when every gold column has a counterpart in the agent's result with the same
values, and the rows line up. Extra agent columns are allowed, so `SELECT species, count(*) AS n`
matches `SELECT count(*), species, 100.0 * count(*) / 344 AS pct`. Row order counts only when the
case says so. Numbers match within rounding to the precision the agent used, or a relative
tolerance of 0.1%.
"""

import math
from collections.abc import Sequence
from typing import Any

REL_TOL = 1e-3
P_VALUE_REL_TOL = 0.05
EFFECT_ABS_TOL = 0.02


def _decimals(x: float) -> int:
    text = repr(x)
    if "e" in text or "." not in text:
        return 0 if "e" not in text else 15
    return len(text.split(".")[1])


def values_match(agent: Any, gold: Any) -> bool:
    if agent is None or gold is None:
        return agent is None and gold is None
    if isinstance(gold, bool) or isinstance(agent, bool):
        return _as_bool(agent) == _as_bool(gold)
    if isinstance(gold, int | float) and isinstance(agent, int | float):
        a, g = float(agent), float(gold)
        if math.isclose(a, g, rel_tol=REL_TOL, abs_tol=1e-9):
            return True
        d = _decimals(a)
        return d < 15 and abs(a - g) <= 0.5 * 10.0 ** (-d) * (1 + 1e-9)
    return str(agent).strip().lower() == str(gold).strip().lower()


def _as_bool(v: Any) -> Any:
    if isinstance(v, str) and v.lower() in ("true", "false", "yes", "no"):
        return v.lower() in ("true", "yes")
    if isinstance(v, int | float):
        return bool(v)
    return v


def _key(v: Any) -> Any:
    """Coarse sort key so close numbers sort together."""
    if v is None:
        return (0, "")
    if isinstance(v, bool):
        return (1, str(int(v)))
    if isinstance(v, int | float):
        return (1, f"{float(v):.2e}")
    return (2, str(v).strip().lower())


def _column(rows: Sequence[Sequence[Any]], i: int) -> list[Any]:
    return [r[i] for r in rows]


def _same_multiset(a: list[Any], g: list[Any]) -> bool:
    if len(a) != len(g):
        return False
    a_sorted, g_sorted = sorted(a, key=_key), sorted(g, key=_key)
    if all(values_match(x, y) for x, y in zip(a_sorted, g_sorted, strict=True)):
        return True
    # Sorting by a coarse key can misalign near-equal numbers; fall back to greedy matching.
    left = list(g)
    for x in a:
        hit = next((j for j, y in enumerate(left) if values_match(x, y)), None)
        if hit is None:
            return False
        left.pop(hit)
    return True


def results_match(
    agent_rows: Sequence[Sequence[Any]],
    gold_rows: Sequence[Sequence[Any]],
    *,
    order_matters: bool = False,
) -> bool:
    if len(agent_rows) != len(gold_rows):
        return False
    if not gold_rows:
        return True
    n_gold, n_agent = len(gold_rows[0]), len(agent_rows[0])
    if n_agent < n_gold:
        return False
    # Candidate agent columns for each gold column, by value multiset.
    candidates = [
        [j for j in range(n_agent) if _same_multiset(_column(agent_rows, j), _column(gold_rows, i))]
        for i in range(n_gold)
    ]
    if any(not c for c in candidates):
        return False
    for mapping in _assignments(candidates):
        projected = [[row[j] for j in mapping] for row in agent_rows]
        if _rows_match(projected, [list(r) for r in gold_rows], order_matters):
            return True
    return False


def _assignments(candidates: list[list[int]], limit: int = 200) -> list[tuple[int, ...]]:
    """Distinct agent columns for each gold column (bounded search)."""
    out: list[tuple[int, ...]] = []

    def walk(i: int, used: tuple[int, ...]) -> None:
        if len(out) >= limit:
            return
        if i == len(candidates):
            out.append(used)
            return
        for j in candidates[i]:
            if j not in used:
                walk(i + 1, (*used, j))

    walk(0, ())
    return out


def _rows_match(agent: list[list[Any]], gold: list[list[Any]], order_matters: bool) -> bool:
    if order_matters:
        return all(
            all(values_match(a, g) for a, g in zip(ar, gr, strict=True))
            for ar, gr in zip(agent, gold, strict=True)
        )
    left = list(agent)
    for gr in gold:
        hit = next(
            (
                k
                for k, ar in enumerate(left)
                if all(values_match(a, g) for a, g in zip(ar, gr, strict=True))
            ),
            None,
        )
        if hit is None:
            return False
        left.pop(hit)
    return True


def stat_results_match(agent: dict[str, Any], gold: dict[str, Any]) -> bool:
    """Same test, p-values agree (both below 0.001, or within 5%), effect sizes within 0.02."""
    if agent.get("test") != gold.get("test"):
        return False
    pa, pg = agent.get("p_value"), gold.get("p_value")
    if pa is None or pg is None:
        return False
    p_ok = (pa < 1e-3 and pg < 1e-3) or math.isclose(pa, pg, rel_tol=P_VALUE_REL_TOL)
    ea = (agent.get("effect_size") or {}).get("value")
    eg = (gold.get("effect_size") or {}).get("value")
    if ea is None or eg is None:
        return False
    # Cliff's delta flips sign with group order; compare magnitudes.
    return p_ok and abs(abs(ea) - abs(eg)) <= EFFECT_ABS_TOL
