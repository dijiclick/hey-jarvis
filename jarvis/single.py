import fcntl
import os
from pathlib import Path
from typing import TextIO


def acquire_lock(home: Path) -> TextIO | None:
    """Hold ~/.jarvis/jarvis.lock for the life of the process; None if another Jarvis has it."""
    home.mkdir(parents=True, exist_ok=True)
    f = open(home / "jarvis.lock", "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f
