import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

HOME_PROJECT_NAME = "home"
MARKERS = (".git", "package.json", "pyproject.toml", "CLAUDE.md", "go.mod", "Cargo.toml")


@dataclass(frozen=True)
class Project:
    name: str
    path: Path


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s_\-.]+", "", s)


def _is_project(d: Path) -> bool:
    return any((d / m).exists() for m in MARKERS)


def load_aliases(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


class ProjectResolver:
    def __init__(self, root: Path, aliases: dict[str, str] | None = None):
        self.root = root
        self.aliases = aliases or {}

    def _scan(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        if not self.root.is_dir():
            return found
        for d in sorted(self.root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            found.setdefault(d.name, d)
            if _is_project(d):
                continue
            try:
                subs = sorted(d.iterdir())
            except PermissionError:
                continue
            for sub in subs:
                if sub.is_dir() and not sub.name.startswith(".") and _is_project(sub):
                    found.setdefault(sub.name, sub)
        return found

    def names(self) -> list[str]:
        return list(self._scan())

    def resolve(self, spoken: str | None) -> Project | None:
        if spoken is None or not spoken.strip():
            return Project(HOME_PROJECT_NAME, Path.home())
        projects = self._scan()
        target = self.aliases.get(spoken.strip())
        if target is not None:
            if target.startswith(("/", "~")):
                p = Path(target).expanduser()
                return Project(p.name, p)
            spoken = target
        key = _norm(spoken)
        normed = {_norm(n): n for n in projects}
        if key in normed:
            n = normed[key]
            return Project(n, projects[n])
        partial = sorted((n for k, n in normed.items() if key and (k.startswith(key) or key in k)), key=len)
        if partial:
            return Project(partial[0], projects[partial[0]])
        close = difflib.get_close_matches(key, list(normed), n=1, cutoff=0.75)
        if close:
            n = normed[close[0]]
            return Project(n, projects[n])
        return None

    def suggestions(self, spoken: str, n: int = 3) -> list[str]:
        normed = {_norm(name): name for name in self._scan()}
        return [normed[k] for k in difflib.get_close_matches(_norm(spoken), list(normed), n=n, cutoff=0.3)]
