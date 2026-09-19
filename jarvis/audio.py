import asyncio
import logging
import queue
import threading
import time

import numpy as np
from livekit import rtc
from livekit.agents.utils import aio
from livekit.agents.voice import io

log = logging.getLogger("jarvis.audio")

SR = 24000
FRAME = 240  # 10 ms at 24 kHz
WAKE_SR = 16000


# measured on this Mac: a silent Bluetooth mic peaks around 9, a live mic in a quiet room 130-550
SILENT_PEAK = 60
PROBE_SECONDS = 0.6


def probe_input(index: int, seconds: float = PROBE_SECONDS) -> int:
    """Peak amplitude from one device, or -1 if it cannot be opened. Bluetooth mics often return pure silence."""
    import numpy as np
    import sounddevice as sd

    try:
        recording = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="int16", device=index)
        sd.wait()
        return int(np.abs(recording[:, 0].astype(np.int32)).max())
    except Exception:
        return -1


def pick_input_device(preference: str | None, devices: list | None = None,
                      default_index: int | None = None, probe=probe_input) -> int | None:
    """Resolve JARVIS_INPUT_DEVICE to a device index; None means "let CoreAudio choose".

    "auto" picks by evidence, not by name: it briefly listens to the system default and keeps it when real audio
    arrives, otherwise tries the other inputs. Choosing by name was wrong in both directions — the built-in mic
    is useless when you wear earbuds, and the default is useless when those earbuds deliver silence.
    """
    if not preference or preference == "default":
        return None
    if devices is None:
        import sounddevice as sd

        devices = list(sd.query_devices())
        if default_index is None:
            default_index = sd.default.device[0]

    inputs = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]

    if preference != "auto":
        for i in inputs:
            if preference.lower() in devices[i]["name"].lower():
                return i
        return None

    # Use the microphone you chose in macOS. No probing at all.
    #
    # Measured on this Mac: opening a Bluetooth mic collapses its SCO link, so probes lie. Six back-to-back opens
    # gave 5766, 558, 10, 9, 5, 7; the same device with a 2s gap gave 5766 every time. Because each selection is
    # itself an open, consecutive calls disagreed and the chosen mic changed on every restart — the probe
    # manufactured the silence it then reacted to. Deafness is detected at runtime instead, from the live input
    # level while a session is open, which costs nothing and cannot be fooled by the act of measuring.
    if default_index in inputs:
        return default_index
    return inputs[0] if inputs else None


def sd_input_stream_type():
    """sounddevice is imported lazily, so resolve InputStream only when it is actually needed."""
    import sounddevice as sd

    return sd.InputStream


def next_input_device(current: int | None, devices: list | None = None,
                      default_index: int | None = None) -> int | None:
    """The next usable input after `current`, for when the one in use has gone deaf.

    Never returns `current`, and never returns the system default once we have moved off it: on this Mac the
    default is a Bluetooth headset that goes silent in music mode, and going back to it just goes deaf again.
    """
    if devices is None:
        import sounddevice as sd

        devices = list(sd.query_devices())
        if default_index is None:
            default_index = sd.default.device[0]
    inputs = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    candidates = [i for i in inputs if i != current and i != default_index]
    if not candidates:
        candidates = [i for i in inputs if i != current]
    if not candidates:
        return None

    # Prefer the built-in microphone: it is physically present and measured 121-207 here, while a Continuity
    # iPhone mic can be in another room and hand back silence. Recovering onto a deaf device helps nobody.
    def rank(index: int) -> tuple[int, int]:
        name = devices[index]["name"].lower()
        if "macbook" in name or "built-in" in name:
            return (0, index)
        if "iphone" in name or "ipad" in name:
            return (2, index)
        return (1, index)

    return min(candidates, key=rank)


def current_input_name(index: int | None) -> str:
    import sounddevice as sd

    try:
        return sd.query_devices(index, kind="input")["name"]
    except Exception:
        return "unknown"


class MicInput(io.AudioInput):
    def __init__(self) -> None:
        super().__init__(label="mic")
        self._ch: aio.Chan[rtc.AudioFrame] = aio.Chan()

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        if not self._ch.closed:
            self._ch.send_nowait(frame)

    def close(self) -> None:
        self._ch.close()

    async def __anext__(self) -> rtc.AudioFrame:
        try:
            return await self._ch.recv()
        except aio.ChanClosed:
            raise StopAsyncIteration from None


class SpeakerOutput(io.AudioOutput):
    """Buffers agent speech; the audio thread pulls it with render()."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(label="speaker", next_in_chain=None, sample_rate=SR,
                         capabilities=io.AudioOutputCapabilities(pause=False))
        self._loop = loop
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._pushed = 0.0
        self._t0 = 0.0
        self._started = False
        self._interrupted = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        if self._flush_task and not self._flush_task.done():
            await self._flush_task
        if not self._pushed:
            self._t0 = time.monotonic()
        self._pushed += frame.duration
        with self._lock:
            self._buf += bytes(frame.data)

    def flush(self) -> None:
        super().flush()
        if self._pushed:
            self._flush_task = asyncio.create_task(self._wait_playout())

    def clear_buffer(self) -> None:
        with self._lock:
            self._buf.clear()
        if not self._pushed:
            return
        if self._flush_task and not self._flush_task.done():
            self._interrupted.set()
            return
        # a segment cleared before flush() would otherwise never report playout
        position = min(time.monotonic() - self._t0, self._pushed)
        self._pushed = 0.0
        self._started = False
        self.on_playback_finished(playback_position=position, interrupted=True)

    async def _drained(self) -> None:
        while True:
            with self._lock:
                if not self._buf:
                    return
            await asyncio.sleep(0.02)

    async def _wait_playout(self) -> None:
        drained = asyncio.create_task(self._drained())
        interrupted = asyncio.create_task(self._interrupted.wait())
        await asyncio.wait({drained, interrupted}, return_when=asyncio.FIRST_COMPLETED)
        was_interrupted = interrupted.done()
        drained.cancel()
        interrupted.cancel()
        position = min(time.monotonic() - self._t0, self._pushed) if was_interrupted else self._pushed
        self.on_playback_finished(playback_position=position, interrupted=was_interrupted)
        self._pushed = 0.0
        self._started = False
        self._interrupted.clear()

    def render(self, nbytes: int) -> bytes:
        with self._lock:
            chunk = bytes(self._buf[:nbytes])
            del self._buf[:nbytes]
        if chunk and not self._started:
            self._started = True
            t = time.time()
            self._loop.call_soon_threadsafe(lambda: self.on_playback_started(created_at=t))
        return chunk.ljust(nbytes, b"\x00")


class LocalAudio:
    """Mic and speaker with WebRTC echo cancellation.

    Mic audio goes to the attached voice session, or (when detached) to wake_queue at 16 kHz.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, input_device=None, output_device=None) -> None:
        self.loop = loop
        self.input_device = input_device
        self.output_device = output_device
        self.apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                             high_pass_filter=True, auto_gain_control=True)
        self.wake_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=500)
        self.mic: MicInput | None = None
        self.speaker: SpeakerOutput | None = None
        self.input_peak = 0
        self._resampler = rtc.AudioResampler(input_rate=SR, output_rate=WAKE_SR, num_channels=1)
        self._chime = bytearray()
        self._chime_lock = threading.Lock()
        self._in_delay = 0.0
        self._out_delay = 0.0
        self._streams: list = []

    def start(self) -> None:
        import sounddevice as sd

        if isinstance(self.input_device, str):
            self.input_device = pick_input_device(self.input_device)
        name = sd.query_devices(self.input_device, kind="input")["name"]
        log.info("microphone: %s", name)
        self._streams = [
            sd.InputStream(callback=self._on_input, dtype="int16", channels=1, samplerate=SR,
                           blocksize=2400, device=self.input_device),
            sd.OutputStream(callback=self._on_output, dtype="int16", channels=1, samplerate=SR,
                            blocksize=2400, device=self.output_device),
        ]
        for s in self._streams:
            s.start()

    def stop(self) -> None:
        for s in self._streams:
            s.stop()
            s.close()
        self._streams = []

    def switch_input(self, index: int | None) -> str:
        """Move to another microphone without dropping the speaker. Returns the new device's name."""
        self.input_device = index
        for stream in list(self._streams):
            if isinstance(stream, sd_input_stream_type()):
                stream.stop()
                stream.close()
                self._streams.remove(stream)
        import sounddevice as sd

        new = sd.InputStream(callback=self._on_input, dtype="int16", channels=1, samplerate=SR,
                             blocksize=2400, device=index)
        new.start()
        self._streams.append(new)
        self.input_level = 0
        name = current_input_name(index)
        log.warning("microphone went silent; switched to %s", name)
        return name

    def attach(self) -> tuple[MicInput, SpeakerOutput]:
        self.detach()
        self.mic, self.speaker = MicInput(), SpeakerOutput(self.loop)
        return self.mic, self.speaker

    def detach(self) -> None:
        if self.mic is not None:
            self.mic.close()
        self.mic = None
        self.speaker = None

    def play_chime(self, freq: float = 880.0, dur: float = 0.12) -> None:
        t = np.arange(int(SR * dur)) / SR
        env = np.minimum(1.0, np.minimum(t, dur - t) / 0.01)
        tone = (0.25 * 32767 * env * np.sin(2 * np.pi * freq * t)).astype(np.int16)
        with self._chime_lock:
            self._chime += tone.tobytes()

    def play_pcm(self, pcm: bytes) -> None:
        """Play recorded 24 kHz 16-bit mono audio over whatever the voice is saying (the recorded greeting)."""
        with self._chime_lock:
            self._chime += pcm[:len(pcm) - len(pcm) % 2]

    def _on_input(self, indata, frames, time_info, status) -> None:
        # input_level is the current block (a live meter for the panel); input_peak is the all-time max
        self.input_level = int(np.abs(indata.astype(np.int32)).max(initial=0))
        self.input_peak = max(self.input_peak, self.input_level)
        self._in_delay = time_info.currentTime - time_info.inputBufferAdcTime
        try:
            self.apm.set_stream_delay_ms(int((self._in_delay + self._out_delay) * 1000))
        except RuntimeError:
            pass
        mic = self.mic
        for i in range(frames // FRAME):
            frame = rtc.AudioFrame(data=indata[i * FRAME:(i + 1) * FRAME, 0].tobytes(), sample_rate=SR,
                                   num_channels=1, samples_per_channel=FRAME)
            self.apm.process_stream(frame)
            if mic is not None:
                self.loop.call_soon_threadsafe(mic.push_frame, frame)
                continue
            for rf in self._resampler.push(frame):
                try:
                    self.wake_queue.put_nowait(np.frombuffer(bytes(rf.data), dtype=np.int16))
                except queue.Full:
                    pass

    def _on_output(self, outdata, frames, time_info, status) -> None:
        self._out_delay = time_info.outputBufferDacTime - time_info.currentTime
        nbytes = frames * 2
        spk = self.speaker
        voice = np.frombuffer(spk.render(nbytes), dtype=np.int16) if spk else np.zeros(frames, np.int16)
        with self._chime_lock:
            chime = bytes(self._chime[:nbytes])
            del self._chime[:nbytes]
        mixed = voice.astype(np.int32)
        if chime:
            mixed += np.frombuffer(chime.ljust(nbytes, b"\x00"), dtype=np.int16)
        out = np.clip(mixed, -32768, 32767).astype(np.int16)
        # what Jarvis is saying right now, so the panel's orb reacts while it speaks
        self.output_level = int(np.abs(out.astype(np.int32)).max(initial=0))
        outdata[:, 0] = out
        for i in range(frames // FRAME):
            self.apm.process_reverse_stream(rtc.AudioFrame(
                data=out[i * FRAME:(i + 1) * FRAME].tobytes(), sample_rate=SR, num_channels=1,
                samples_per_channel=FRAME))
