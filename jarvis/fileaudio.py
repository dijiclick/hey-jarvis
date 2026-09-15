import asyncio
import queue
import wave
from pathlib import Path

import numpy as np
from livekit import rtc

from .audio import FRAME, SR, MicInput, SpeakerOutput


class FileAudio:
    """Scripted stand-in for LocalAudio: plays WAV clips as the mic and records the speaker."""

    def __init__(self, loop: asyncio.AbstractEventLoop, clips: list[Path], gap_s: float = 20.0):
        self.loop = loop
        self.gap_s = gap_s
        self.wake_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.captured = bytearray()
        self.mic: MicInput | None = None
        self.speaker: SpeakerOutput | None = None
        self.finished = False
        self._done = asyncio.Event()
        self._pcm = [self._load(Path(c)) for c in clips]
        self._tasks: list[asyncio.Task[None]] = []

    @staticmethod
    def _load(path: Path) -> bytes:
        with wave.open(str(path)) as w:
            if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"{path} must be 24 kHz mono 16-bit")
            return w.readframes(w.getnframes())

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._feed()), asyncio.create_task(self._drain_speaker())]

    def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    def attach(self) -> tuple[MicInput, SpeakerOutput]:
        self.detach()
        self.mic, self.speaker = MicInput(), SpeakerOutput(self.loop)
        return self.mic, self.speaker

    def detach(self) -> None:
        if self.mic is not None:
            self.mic.close()
        self.mic = self.speaker = None

    def play_chime(self, freq: float = 880.0, dur: float = 0.12) -> None:
        pass

    async def wait_finished(self) -> None:
        await self._done.wait()

    def _push(self, data: bytes) -> None:
        if self.mic is not None:
            self.mic.push_frame(rtc.AudioFrame(data=data, sample_rate=SR, num_channels=1, samples_per_channel=FRAME))

    async def _feed(self) -> None:
        silence = b"\x00" * FRAME * 2
        timeline: list[bytes] = []
        for pcm in self._pcm:
            timeline.append(pcm)
            timeline.append(silence * int(self.gap_s * 100))
        loop = asyncio.get_running_loop()
        start = loop.time()
        sent = 0
        for block in timeline:
            for i in range(0, len(block), FRAME * 2):
                self._push(block[i:i + FRAME * 2].ljust(FRAME * 2, b"\x00"))
                sent += 1
                delay = start + sent * 0.01 - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
        self.finished = True
        self._done.set()
        while True:
            self._push(silence)
            await asyncio.sleep(0.01)

    async def _drain_speaker(self) -> None:
        while True:
            await asyncio.sleep(0.01)
            if self.speaker is not None:
                self.captured += self.speaker.render(FRAME * 2)
