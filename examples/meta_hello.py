"""Meta-harness smoke test — routes a moderate task through the team.

Usage:
    uv run python examples/meta_hello.py
"""

from __future__ import annotations

from dotenv import load_dotenv

from langchain_harness.meta import MetaHarness


TASK = (
    "Draft a 5-line summary of what an agent harness is, then save it to "
    "_workspace/meta/hello_summary.md and report the path."
)


def main() -> None:
    load_dotenv()
    mh = MetaHarness()
    out = mh.run(TASK)
    print("=== FINAL ===")
    final = out["final"]
    print(getattr(final, "content", final))
    print(f"\nTrace: {out['trace_path']}")
    print(f"Roles used: {', '.join(out['spec'].required_roles)}")


if __name__ == "__main__":
    main()
