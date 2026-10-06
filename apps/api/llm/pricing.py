from collections.abc import Mapping
from decimal import Decimal

PER_MILLION = Decimal(1_000_000)


def cost_usd(
    prices: Mapping[str, tuple[float, float]], model: str, input_tokens: int, output_tokens: int
) -> Decimal:
    """Cost of one call. Models missing from the table are treated as free."""
    rate = prices.get(model)
    if rate is None:
        return Decimal(0)
    input_rate, output_rate = (Decimal(str(r)) for r in rate)
    return (input_rate * input_tokens + output_rate * output_tokens) / PER_MILLION
