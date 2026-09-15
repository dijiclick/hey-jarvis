import logging
import os
import queue
import threading
import time
from collections.abc import Callable

import numpy as np
import openwakeword

log = logging.getLogger("jarvis.ears")

HEY_JARVIS_MODEL = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models", "hey_jarvis_v0.1.onnx")
CHUNK = 1280  # 80 ms at 16 kHz


class WakeWordDetector:
    def __init__(self, threshold: float = 0.5, cooldown_s: float = 2.0, model=None,
                 clock: Callable[[], float] = time.monotonic):
        if model is None:
            from openwakeword.model import Model

            model = Model(wakeword_model_paths=[HEY_JARVIS_MODEL])
        self.model = model
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self._buf = np.zeros(0, np.int16)
        self._last = -1e9

    def process(self, pcm: np.ndarray) -> bool:
        self._buf = np.concatenate([self._buf, pcm.astype(np.int16)])
        fired = False
        while len(self._buf) >= CHUNK:
            chunk, self._buf = self._buf[:CHUNK], self._buf[CHUNK:]
            score = max(self.model.predict(chunk).values())
            now = self.clock()
            if score >= self.threshold and now - self._last >= self.cooldown_s:
                self._last = now
                self.model.reset()
                fired = True
        return fired


def accessibility_trusted(prompt: bool = False) -> bool:
    """Whether macOS lets this app watch global keys; prompt=True lists Jarvis in Accessibility settings."""
    try:
        import HIServices
    except ImportError:
        return True
    if prompt:
        return bool(HIServices.AXIsProcessTrustedWithOptions({HIServices.kAXTrustedCheckOptionPrompt: True}))
    return bool(HIServices.AXIsProcessTrusted())


class Ears:
    def __init__(self, wake_queue: "queue.Queue[np.ndarray]", detector: WakeWordDetector,
                 on_wake: Callable[[], None], hotkey: str | None,
                 trust_check: Callable[..., bool] = accessibility_trusted):
        self.wake_queue = wake_queue
        self.detector = detector
        self.on_wake = on_wake
        self.hotkey = hotkey
        self.trust_check = trust_check
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hotkeys = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                pcm = self.wake_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                if self.detector.process(pcm):
                    log.info("wake word detected")
                    self.on_wake()
            except Exception:
                log.exception("wake word processing failed")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="jarvis-ears", daemon=True)
        self._thread.start()
        if self.hotkey:
            from pynput import keyboard

            trusted = self.trust_check(prompt=True)
            log.info("hotkey %s, accessibility trusted: %s", self.hotkey, trusted)
            if not trusted:
                log.warning("the hotkey needs Accessibility permission; macOS was asked to list Jarvis in "
                            "System Settings > Privacy & Security > Accessibility (restart Jarvis after allowing)")
            from .hotkey import HotkeyMatcher

            matcher = HotkeyMatcher(self.hotkey)

            def on_press(key) -> None:
                if matcher.press(key):
                    log.info("hotkey pressed")
                    self.on_wake()

            self._hotkeys = keyboard.Listener(on_press=on_press, on_release=matcher.release)
            self._hotkeys.start()

    def stop(self) -> None:
        self._stop.set()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)
