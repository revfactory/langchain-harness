from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MemoryStore:
    """Persistence layer for AGENTS.md + per-run traces + improvement cards."""

    workspace: Path
    agents_md: Path | None = None

    def __post_init__(self) -> None:
        (self.workspace / "runs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "meta").mkdir(parents=True, exist_ok=True)

    def load_agents_md(self) -> str:
        if self.agents_md and self.agents_md.exists():
            return self.agents_md.read_text()
        return ""

    def recent_runs(self, limit: int = 10) -> list[Path]:
        files = sorted((self.workspace / "runs").glob("meta_*.jsonl"), reverse=True)
        return files[:limit]

    def append_card(self, card: dict) -> Path:
        path = self.workspace / "meta" / "improvement_cards.jsonl"
        enriched = dict(card)
        enriched["ts"] = datetime.now(timezone.utc).isoformat()
        with path.open("a") as f:
            f.write(json.dumps(enriched, ensure_ascii=False) + "\n")
        return path

    def cards(self) -> list[dict]:
        path = self.workspace / "meta" / "improvement_cards.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
