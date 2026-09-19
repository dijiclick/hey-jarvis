"""Long-term memory: Mem0 learns lasting facts from every finished conversation and keeps them on this Mac.

Before this, a new conversation carried four transcript lines and whatever the user had explicitly asked it to
remember, so it went looking for a WhatsApp app every time. Now "the user uses WhatsApp Web in Chrome" or "Sam is
the user's colleague" is learned once and read back into the voice and into Claude through ~/.jarvis/memories.md.
"""
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .profile import memories_path

# Mem0 reports usage to PostHog by default; a personal assistant's memory stays private
os.environ.setdefault("MEM0_TELEMETRY", "False")

log = logging.getLogger("jarvis.memory")

OWNER = "owner"
EXTRACT_MODEL = "gemini-3.5-flash-lite"  # gemini-2.5-flash-lite is no longer offered to new keys
EMBED_MODEL = "models/gemini-embedding-001"
EMBED_DIMS = 768

__all__ = ["LongTermMemory", "mem0_config", "memories_path"]


def mem0_config(home: Path, api_key: str) -> dict[str, Any]:
    folder = home / "memory"
    return {
        "llm": {"provider": "gemini", "config": {"model": EXTRACT_MODEL, "api_key": api_key, "temperature": 0.1}},
        "embedder": {"provider": "gemini",
                     "config": {"model": EMBED_MODEL, "api_key": api_key, "embedding_dims": EMBED_DIMS}},
        "vector_store": {"provider": "qdrant",
                         "config": {"collection_name": "jarvis", "path": str(folder / "qdrant"), "on_disk": True,
                                    "embedding_model_dims": EMBED_DIMS}},
        "history_db_path": str(folder / "history.db"),
    }


def _build_mem0(config: dict[str, Any]):
    from mem0 import Memory  # imported on first use: it is slow to load and Jarvis should start fast

    return Memory.from_config(config)


class LongTermMemory:
    def __init__(self, home: Path, api_key: str | None, factory: Callable[[dict[str, Any]], Any] = _build_mem0):
        self.home = home
        self.api_key = api_key
        self._factory = factory
        self._mem0 = None
        self._lock = threading.Lock()

    def _memory(self):
        with self._lock:
            if self._mem0 is None:
                self._mem0 = self._factory(mem0_config(self.home, self.api_key))
            return self._mem0

    def learn(self, turns: list[tuple[str, str]]) -> None:
        """Extract lasting facts from a finished conversation and refresh memories.md. Never raises."""
        if not self.api_key:
            return
        messages = [{"role": role, "content": text.strip()} for role, text in turns
                    if role in ("user", "assistant") and text.strip() and text.strip() != "<noise>"]
        if not any(m["role"] == "user" for m in messages):
            return
        try:
            memory = self._memory()
            memory.add(messages, user_id=OWNER)
            facts = [item["memory"] for item in memory.get_all(filters={"user_id": OWNER}).get("results", [])]
            path = memories_path(self.home)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(f"- {fact}\n" for fact in facts), encoding="utf-8")
            log.info("memory: learned from a %d-line conversation; %d facts known", len(messages), len(facts))
        except Exception:
            log.exception("memory: could not learn from the conversation")
