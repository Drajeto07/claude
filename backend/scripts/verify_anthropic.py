"""Manual-only connectivity check for the Anthropic adapter.

Run explicitly from backend/, with ANTHROPIC_API_KEY set in backend/.env:

    .\\venv\\Scripts\\python.exe -m scripts.verify_anthropic

Not part of app startup — nothing in app/ imports this module or calls
app.ai.factory.get_ai_provider() automatically, so it can't fire on its own.
"""

import asyncio

from app.ai.factory import get_ai_provider


async def main() -> None:
    provider = get_ai_provider()
    print(f"Using provider: {provider.provider_name()}")
    reply = await provider.complete("Reply with only the single word: pong", max_tokens=16)
    print(f"Reply: {reply!r}")


if __name__ == "__main__":
    asyncio.run(main())
