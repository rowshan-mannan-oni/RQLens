"""Make one traced LLM call to check the provider settings.

Run: docker compose exec api python -m api.llm.smoke
"""

import asyncio

from pydantic import BaseModel

from api.llm.client import LLMClient


class Reply(BaseModel):
    answer: str
    confidence: float


async def main() -> None:
    client = LLMClient.from_settings()
    result = await client.complete_structured(
        [
            {"role": "system", "content": "You answer briefly and return JSON."},
            {"role": "user", "content": "In one sentence: what is a research question?"},
        ],
        Reply,
        step="smoke",
        prompt_version="smoke-v1",
    )
    print(f"model={result.model} tokens={result.input_tokens}+{result.output_tokens}")
    print(f"cost=${result.cost_usd} latency={result.latency_ms}ms")
    print(result.parsed)


if __name__ == "__main__":
    asyncio.run(main())
