"""The autonomy level: how much Claude may do without a spoken yes. Saved in ~/.jarvis so it survives restarts."""
import json
import logging
from pathlib import Path

from .guard import DEFAULT_LEVEL, LEVELS

log = logging.getLogger("jarvis.autonomy")


class Autonomy:
    def __init__(self, path: Path | None, default: str = DEFAULT_LEVEL, hub=None):
        self.path = path
        self.hub = hub
        self._level = default if default in LEVELS else DEFAULT_LEVEL
        try:
            saved = json.loads(path.read_text()).get("level") if path else None
        except (OSError, ValueError, AttributeError):
            saved = None
        if saved in LEVELS:
            self._level = saved

    def get(self) -> str:
        return self._level

    def set(self, level: str) -> bool:
        """Switch level; call from the asyncio loop thread, because it publishes to the panel."""
        if level not in LEVELS:
            return False
        self._level = level
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({"level": level}))
            except OSError as e:
                log.warning("autonomy level not saved: %s", e)
        log.info("autonomy level: %s", level)
        if self.hub is not None:
            self.hub.publish("autonomy", level=level)
        return True
