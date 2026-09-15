import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from livekit import rtc

from jarvis.audio import LocalAudio, pick_input_device

DEVICES = [
    {"name": "iPhone Microphone", "max_input_channels": 1},
    {"name": "AirPods Pro", "max_input_channels": 1},
    {"name": "AirPods Pro", "max_input_channels": 0},
    {"name": "MacBook Air Microphone", "max_input_channels": 1},
]


# device selection is covered by tests/test_input_device.py, which injects a fake probe
# instead of opening the real microphone

TI = SimpleNamespace(currentTime=1.0, inputBufferAdcTime=0.99, outputBufferDacTime=1.01)


def block(value=0, n=2400):
    return np.full((n, 1), value, np.int16)


def frame_of(samples, value=0):
    return rtc.AudioFrame(data=np.full(samples, value, np.int16).tobytes(), sample_rate=24000,
                          num_channels=1, samples_per_channel=samples)


async def test_input_peak_tracks_loudest_sample():
    a = LocalAudio(asyncio.get_running_loop())
    assert a.input_peak == 0
    a._on_input(block(-500), 2400, TI, None)
    a._on_input(block(200), 2400, TI, None)
    assert a.input_peak == 500


async def test_mic_frames_route_to_session_when_attached():
    a = LocalAudio(asyncio.get_running_loop())
    mic, _ = a.attach()
    a._on_input(block(), 2400, TI, None)
    frames = [await asyncio.wait_for(mic.__anext__(), 1) for _ in range(10)]
    assert all(f.samples_per_channel == 240 and f.sample_rate == 24000 for f in frames)
    assert a.wake_queue.empty()


async def test_mic_frames_route_to_wake_queue_when_detached():
    a = LocalAudio(asyncio.get_running_loop())
    for _ in range(5):
        a._on_input(block(), 2400, TI, None)
    total = 0
    while not a.wake_queue.empty():
        total += len(a.wake_queue.get_nowait())
    assert 6000 <= total <= 8000


async def test_speaker_plays_and_reports_playout():
    a = LocalAudio(asyncio.get_running_loop())
    _, spk = a.attach()
    await spk.capture_frame(frame_of(2400, 1000))
    spk.flush()
    out = block()
    a._on_output(out, 2400, TI, None)
    ev = await asyncio.wait_for(spk.wait_for_playout(), 1)
    assert ev.interrupted is False
    assert ev.playback_position == pytest.approx(0.1)
    assert out[:, 0].max() == 1000


async def test_clear_buffer_interrupts_flushed_segment():
    a = LocalAudio(asyncio.get_running_loop())
    _, spk = a.attach()
    await spk.capture_frame(frame_of(24000))
    spk.flush()
    spk.clear_buffer()
    ev = await asyncio.wait_for(spk.wait_for_playout(), 1)
    assert ev.interrupted is True


async def test_clear_buffer_interrupts_unflushed_segment():
    a = LocalAudio(asyncio.get_running_loop())
    _, spk = a.attach()
    await spk.capture_frame(frame_of(24000))
    spk.clear_buffer()
    ev = await asyncio.wait_for(spk.wait_for_playout(), 1)
    assert ev.interrupted is True


async def test_chime_plays_without_session():
    a = LocalAudio(asyncio.get_running_loop())
    a.play_chime()
    out = block()
    a._on_output(out, 2400, TI, None)
    assert np.abs(out).max() > 0


async def test_detach_closes_mic():
    a = LocalAudio(asyncio.get_running_loop())
    mic, _ = a.attach()
    a.detach()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(mic.__anext__(), 1)
