import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL, cwd TEXT NOT NULL, task TEXT NOT NULL,
  status TEXT NOT NULL, result TEXT, created REAL NOT NULL, finished REAL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS transcripts(
  id INTEGER PRIMARY KEY, role TEXT NOT NULL, text TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(project TEXT PRIMARY KEY, session_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS voice_sessions(id INTEGER PRIMARY KEY, started REAL NOT NULL, ended REAL NOT NULL);
CREATE TABLE IF NOT EXISTS routines(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, schedule TEXT NOT NULL, task TEXT NOT NULL,
  project TEXT, next_run REAL, last_run REAL, enabled INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
"""

FINAL = ("done", "failed", "cancelled")


@dataclass
class Job:
    id: int
    project: str
    cwd: str
    task: str
    status: str
    result: str | None
    created: float
    finished: float | None


@dataclass
class Routine:
    id: int
    name: str
    schedule: str
    task: str
    project: str | None
    next_run: float | None
    last_run: float | None
    enabled: bool
    created: float


class Store:
    def __init__(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def create_job(self, project: str, cwd: str, task: str) -> int:
        cur = self._exec(
            "INSERT INTO jobs(project, cwd, task, status, created) VALUES (?,?,?,?,?)",
            (project, cwd, task, "queued", time.time()),
        )
        return int(cur.lastrowid)

    def set_status(self, job_id: int, status: str, result: str | None = None) -> None:
        finished = time.time() if status in FINAL else None
        self._exec(
            "UPDATE jobs SET status=?, result=COALESCE(?, result), finished=? WHERE id=?",
            (status, result, finished, job_id),
        )

    def _jobs(self, where: str, args: tuple = ()) -> list[Job]:
        rows = self._exec(
            f"SELECT id, project, cwd, task, status, result, created, finished FROM jobs {where}", args
        ).fetchall()
        return [Job(*r) for r in rows]

    def get_job(self, job_id: int) -> Job | None:
        jobs = self._jobs("WHERE id=?", (job_id,))
        return jobs[0] if jobs else None

    def active_jobs(self) -> list[Job]:
        return self._jobs("WHERE status IN ('queued','running') ORDER BY id")

    def jobs_since(self, ts: float) -> list[Job]:
        return self._jobs("WHERE created>=? ORDER BY id", (ts,))

    def fail_stale_jobs(self) -> int:
        cur = self._exec(
            "UPDATE jobs SET status='failed', result='Interrupted by a Jarvis restart.', finished=? "
            "WHERE status IN ('queued','running')",
            (time.time(),),
        )
        return cur.rowcount

    def add_event(self, job_id: int, kind: str, text: str) -> None:
        self._exec("INSERT INTO events(job_id, kind, text, ts) VALUES (?,?,?,?)", (job_id, kind, text, time.time()))

    def recent_events(self, job_id: int, limit: int = 5) -> list[str]:
        rows = self._exec(
            "SELECT text FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)
        ).fetchall()
        return [r[0] for r in reversed(rows)]

    def add_transcript(self, role: str, text: str) -> None:
        self._exec("INSERT INTO transcripts(role, text, ts) VALUES (?,?,?)", (role, text, time.time()))

    def recent_transcripts(self, limit: int = 20) -> list[tuple[str, str]]:
        rows = self._exec("SELECT role, text FROM transcripts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [(r[0], r[1]) for r in reversed(rows)]

    def add_voice_session(self, started: float, ended: float) -> None:
        self._exec("INSERT INTO voice_sessions(started, ended) VALUES (?,?)", (started, ended))

    def voice_seconds_since(self, ts: float) -> float:
        row = self._exec(
            "SELECT COALESCE(SUM(ended - MAX(started, ?)), 0) FROM voice_sessions WHERE ended > ?", (ts, ts)
        ).fetchone()
        return float(row[0])

    # ---- routines ----------------------------------------------------------

    def _routines(self, where: str, args: tuple = ()) -> list[Routine]:
        rows = self._exec(
            f"SELECT id, name, schedule, task, project, next_run, last_run, enabled, created FROM routines {where}",
            args,
        ).fetchall()
        return [Routine(*r[:7], bool(r[7]), r[8]) for r in rows]

    def add_routine(self, name: str, schedule: str, task: str, project: str | None, next_run: float | None) -> int:
        cur = self._exec(
            "INSERT INTO routines(name, schedule, task, project, next_run, enabled, created) "
            "VALUES (?,?,?,?,?,1,?) "
            "ON CONFLICT(name) DO UPDATE SET schedule=excluded.schedule, task=excluded.task, "
            "project=excluded.project, next_run=excluded.next_run, enabled=1",
            (name, schedule, task, project, next_run, time.time()),
        )
        return int(cur.lastrowid)

    def list_routines(self) -> list[Routine]:
        return self._routines("ORDER BY name")

    def get_routine(self, name: str) -> Routine | None:
        found = self._routines("WHERE name=?", (name,))
        return found[0] if found else None

    def due_routines(self, now: float) -> list[Routine]:
        return self._routines("WHERE enabled=1 AND next_run IS NOT NULL AND next_run<=? ORDER BY next_run", (now,))

    def mark_routine_run(self, routine_id: int, ran_at: float, next_run: float | None) -> None:
        self._exec("UPDATE routines SET last_run=?, next_run=?, enabled=? WHERE id=?",
                   (ran_at, next_run, 1 if next_run is not None else 0, routine_id))

    def set_routine_enabled(self, name: str, enabled: bool, next_run: float | None = None) -> bool:
        cur = self._exec("UPDATE routines SET enabled=?, next_run=COALESCE(?, next_run) WHERE name=?",
                         (1 if enabled else 0, next_run, name))
        return cur.rowcount > 0

    def remove_routine(self, name: str) -> bool:
        return self._exec("DELETE FROM routines WHERE name=?", (name,)).rowcount > 0

    def get_session(self, project: str) -> str | None:
        row = self._exec("SELECT session_id FROM sessions WHERE project=?", (project,)).fetchone()
        return row[0] if row else None

    def set_session(self, project: str, session_id: str) -> None:
        self._exec(
            "INSERT INTO sessions(project, session_id) VALUES (?,?) "
            "ON CONFLICT(project) DO UPDATE SET session_id=excluded.session_id",
            (project, session_id),
        )
