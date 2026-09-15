"""Approve Chrome's "Allow remote debugging?" prompt for Jarvis.

Chrome asks on every new debugging connection and can't remember the answer. The clicker is armed only for a short
window right after Jarvis's own browser tool runs, and it presses Allow only on the dialog that mentions remote
debugging, so it never approves unrelated prompts. It uses the native Accessibility API: AppleScript can see the
dialog's sheet but not its buttons.
"""
import logging
import subprocess
import threading
import time
from collections.abc import Callable, Iterator

log = logging.getLogger("jarvis.chrome_consent")

MAX_DEPTH = 14


def pick_allow(nodes: list[tuple[str, str]]) -> int | None:
    """Index of the Allow button if (role, label) nodes are Chrome's remote debugging dialog, else None."""
    if not any("remote debugging" in label.lower() for _, label in nodes):
        return None
    for i, (role, label) in enumerate(nodes):
        if role == "AXButton" and label.split(" | ")[0].strip().lower() == "allow":
            return i
    return None


def _attr(el, name: str):
    import HIServices as AX

    err, val = AX.AXUIElementCopyAttributeValue(el, name, None)
    return val if err == 0 else None


def _walk(el, depth: int = 0) -> Iterator:
    yield el
    if depth < MAX_DEPTH:
        for child in _attr(el, "AXChildren") or []:
            yield from _walk(child, depth + 1)


def _label(el) -> str:
    parts = (_attr(el, "AXTitle"), _attr(el, "AXDescription"), _attr(el, "AXValue"))
    return " | ".join(str(p) for p in parts if p not in (None, ""))


class ChromeAX:
    """Looks for the consent sheet on Chrome's windows and presses Allow."""

    def __init__(self) -> None:
        self._pid: int | None = None
        self._app = None

    def _chrome(self):
        import HIServices as AX

        out = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True, text=True).stdout.split()
        pid = int(out[0]) if out else None
        if pid is None:
            self._pid = self._app = None
            return None
        if pid != self._pid:
            self._pid = pid
            self._app = AX.AXUIElementCreateApplication(pid)
            AX.AXUIElementSetAttributeValue(self._app, "AXManualAccessibility", True)
        return self._app

    def _find(self):
        """(window, allow_button) for an open consent sheet, "consent without button", or None."""
        app = self._chrome()
        if app is None:
            return None
        for window in _attr(app, "AXWindows") or []:
            for child in _attr(window, "AXChildren") or []:
                if _attr(child, "AXRole") != "AXSheet":
                    continue
                elements = list(_walk(child))
                nodes = [(_attr(el, "AXRole") or "", _label(el)) for el in elements]
                index = pick_allow(nodes)
                if index is not None:
                    return window, elements[index]
                if any("remote debugging" in label.lower() for _, label in nodes):
                    return "consent without button"
        return None

    def press_allow(self) -> str:
        import HIServices as AX

        if self._chrome() is None:
            return "no chrome"
        found = self._find()
        if found is None:
            return "none"
        if found == "consent without button":
            return found
        window, button = found
        # Chrome reports AXPress as done but ignores it unless the window is raised and the button focused
        AX.AXUIElementPerformAction(window, "AXRaise")
        AX.AXUIElementSetAttributeValue(button, "AXFocused", True)
        AX.AXUIElementPerformAction(button, "AXPress")
        time.sleep(0.5)
        return "press failed" if self._find() is not None else "clicked"


class ChromeConsentClicker:
    def __init__(self, window_s: float = 45.0, interval_s: float = 0.3,
                 runner: Callable[[], str] | None = None, clock: Callable[[], float] = time.monotonic):
        self.window_s = window_s
        self.interval_s = interval_s
        self.runner = runner or ChromeAX().press_allow
        self.clock = clock
        self.clicks = 0
        self._armed_until = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reported: set[str] = set()

    def arm(self) -> None:
        """Watch for the prompt during the next window_s seconds."""
        with self._lock:
            self._armed_until = self.clock() + self.window_s
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="jarvis-chrome-consent", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if self.clock() >= self._armed_until:
                    self._thread = None
                    return
            try:
                result = self.runner()
            except Exception as e:
                result = f"error: {type(e).__name__}"
            if result == "clicked":
                self.clicks += 1
                log.info("approved Chrome's remote debugging prompt for Jarvis")
            elif result not in ("none", "no chrome") and result not in self._reported:
                self._reported.add(result)
                log.warning("Chrome consent clicker: %s", result)
            self._stop.wait(self.interval_s)

    def stop(self) -> None:
        self._stop.set()
