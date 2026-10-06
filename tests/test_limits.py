"""Per-user limits: month boundaries and AI budget checks."""

import datetime as dt
from decimal import Decimal

from api.limits import AIUsage, month_start, next_month, over_limit_message


def usage(calls: int, cost: str, call_limit: int = 100, budget: float = 5.0) -> AIUsage:
    return AIUsage(calls, Decimal(cost), call_limit, budget, dt.date(2026, 11, 1))


def test_month_boundaries() -> None:
    now = dt.datetime(2026, 10, 6, 15, 30, tzinfo=dt.UTC)
    assert month_start(now) == dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    assert next_month(now) == dt.date(2026, 11, 1)
    assert next_month(dt.datetime(2026, 12, 31, 23, 59, tzinfo=dt.UTC)) == dt.date(2027, 1, 1)


def test_under_limits() -> None:
    assert usage(99, "4.99").exceeded is None
    assert over_limit_message(usage(99, "4.99")) is None


def test_call_limit_applies_to_free_models() -> None:
    reason = usage(100, "0").exceeded
    assert reason == "100 of 100 AI calls this month"


def test_cost_budget() -> None:
    assert usage(5, "5.00").exceeded == "$5.00 of the $5.00 monthly AI budget"
    message = over_limit_message(usage(5, "7.25"))
    assert message and "resets on 01 November 2026" in message


def test_zero_means_no_limit() -> None:
    assert usage(10_000, "999", call_limit=0, budget=0).exceeded is None
