import os
import queue
import threading
import wave
from pathlib import Path

import numpy as np
import pytest

from jarvis.ears import CHUNK, Ears, WakeWordDetector


class FakeModel:
    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0

    def predict(self, chunk):
        assert len(chunk) == CHUNK
        return {"hey_jarvis_v0.1": self.scores.pop(0) if self.scores else 0.0}

    def reset(self):
        self.resets += 1


def test_fires_once_with_cooldown():
    now = [0.0]
    d = WakeWordDetector(threshold=0.5, cooldown_s=2, model=FakeModel([0.1, 0.9, 0.95]), clock=lambda: now[0])
    assert d.process(np.zeros(CHUNK * 2, np.int16)) is True
    assert d.process(np.zeros(CHUNK, np.int16)) is False
    assert d.model.resets == 1


def test_buffers_partial_chunks():
    d = WakeWordDetector(model=FakeModel([0.9]))
    assert d.process(np.zeros(CHUNK // 2, np.int16)) is False
    assert d.process(np.zeros(CHUNK // 2, np.int16)) is True


def test_ears_thread_calls_on_wake():
    q = queue.Queue()
    hit = threading.Event()
    ears = Ears(q, WakeWordDetector(model=FakeModel([0.9])), on_wake=hit.set, hotkey=None)
    ears.start()
    q.put(np.zeros(CHUNK, np.int16))
    assert hit.wait(2)
    ears.stop()


def test_hotkey_requests_accessibility_and_wakes_on_physical_keys(monkeypatch):
    import pynput.keyboard as kb
    from pynput.keyboard import Key, KeyCode

    listeners = []

    class FakeListener:
        def __init__(self, on_press=None, on_release=None):
            listeners.append((on_press, on_release))

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(kb, "Listener", FakeListener)
    calls, woke = [], []
    ears = Ears(queue.Queue(), WakeWordDetector(model=FakeModel([])), on_wake=lambda: woke.append(True),
                hotkey="<ctrl>+<alt>+j", trust_check=lambda prompt: calls.append(prompt) or False)
    ears.start()
    on_press, _ = listeners[0]
    on_press(Key.ctrl)
    on_press(Key.alt)
    on_press(KeyCode(vk=38, char="∆"))
    ears.stop()
    assert calls == [True]
    assert woke == [True]


@pytest.mark.skipif(not os.environ.get("JARVIS_SLOW"), reason="loads the real wake model")
def test_real_model_detects_hey_jarvis_and_ignores_silence():
    with wave.open(str(Path(__file__).parent / "fixtures" / "hey_jarvis_16k.wav")) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
    assert WakeWordDetector().process(pcm) is True
    assert WakeWordDetector().process(np.zeros(16000 * 3, np.int16)) is False
