"""Minimal smoke test — proves the harness boots and answers a trivial question.

Requires ANTHROPIC_API_KEY in the environment.

    uv run python examples/hello.py
"""

from __future__ import annotations

from dotenv import load_dotenv

from langchain_harness import HarnessConfig, create


def main() -> None:
    load_dotenv()
    agent = create(HarnessConfig(system_prompt="Reply with a single word."))
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Say the word 'ready'."}]}
    )
    final = result["messages"][-1]
    print(getattr(final, "content", final))


if __name__ == "__main__":
    main()
