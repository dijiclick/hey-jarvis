import asyncio
import wave

import numpy as np

from jarvis.fileaudio import FileAudio


def write_wav(path, seconds, value=500):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(np.full(int(24000 * seconds), value, np.int16).tobytes())


async def test_file_audio_feeds_clip_then_silence(tmp_path):
    clip = tmp_path / "a.wav"
    write_wav(clip, 0.2)
    fa = FileAudio(asyncio.get_running_loop(), [clip], gap_s=0.1)
    mic, _ = fa.attach()
    fa.start()
    frames = [await asyncio.wait_for(mic.__anext__(), 1) for _ in range(30)]
    values = [np.frombuffer(bytes(f.data), np.int16).max() for f in frames]
    assert values[0] == 500 and values[-1] == 0
    await asyncio.wait_for(fa.wait_finished(), 2)
    fa.stop()


async def test_file_audio_captures_speaker(tmp_path):
    from livekit import rtc

    clip = tmp_path / "a.wav"
    write_wav(clip, 0.05)
    fa = FileAudio(asyncio.get_running_loop(), [clip], gap_s=0.0)
    _, spk = fa.attach()
    fa.start()
    await spk.capture_frame(rtc.AudioFrame(data=np.full(2400, 700, np.int16).tobytes(), sample_rate=24000,
                                           num_channels=1, samples_per_channel=2400))
    spk.flush()
    await asyncio.wait_for(spk.wait_for_playout(), 2)
    assert np.frombuffer(bytes(fa.captured), np.int16).max() == 700
    fa.stop()
