"""The spoken hello after "Hey Jarvis" and the "bye bye" before Jarvis turns off, recorded once and played from disk.

Asking the live voice model to greet took 2.5-6 s and about one time in five never started at all, so the user
heard nothing and thought Jarvis was broken. A clip recorded with Gemini's text-to-speech, in the same voice, plays
the moment the conversation opens.
"""
import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger("jarvis.greeting")

TTS_MODEL = "gemini-2.5-flash-preview-tts"
ATTEMPTS = 3
GREETINGS = {
    "English": "Hi! How can I help you?",
    "Persian": "سلام! چه کاری برات انجام بدم؟",
    "Turkish": "Merhaba! Nasıl yardımcı olabilirim?",
    "Russian": "Привет! Чем могу помочь?",
}
FAREWELLS = {
    "English": "Bye bye!",
    "Persian": "خداحافظ!",
    "Turkish": "Görüşürüz!",
    "Russian": "Пока-пока!",
}
TEXTS = {"greeting": GREETINGS, "farewell": FAREWELLS}

Synth = Callable[[str, str], Awaitable[bytes]]


def greeting_text(language: str) -> str | None:
    return GREETINGS.get(language)


def farewell_text(language: str) -> str | None:
    return FAREWELLS.get(language)


def greeting_path(home: Path, voice: str, language: str, kind: str = "greeting") -> Path:
    safe = re.sub(r"[^\w-]", "_", f"{voice}-{language}")
    return home / "greetings" / (f"{safe}.pcm" if kind == "greeting" else f"{kind}-{safe}.pcm")


def load_greeting(home: Path | None, voice: str, language: str, kind: str = "greeting") -> bytes | None:
    """The recorded clip as 24 kHz 16-bit mono PCM, or None when there isn't one yet."""
    if home is None:
        return None
    try:
        return greeting_path(home, voice, language, kind).read_bytes() or None
    except OSError:
        return None


async def ensure_greeting(home: Path, voice: str, language: str, synth: Synth, kind: str = "greeting") -> Path | None:
    """Record the hello (or the farewell) for this voice and language unless it already exists."""
    text = TEXTS[kind].get(language)
    if text is None:
        return None
    path = greeting_path(home, voice, language, kind)
    if path.exists() and path.stat().st_size:
        return path
    pcm, problem = b"", "no audio"
    # the TTS preview model sometimes answers with no audio, then works on the next try
    for _ in range(ATTEMPTS):
        try:
            pcm = await synth(text, voice)
        except Exception as e:
            problem = f"{type(e).__name__}: {e}"
            continue
        if pcm:
            break
    if not pcm:
        log.warning("%s not recorded (%s); the voice model will speak it instead", kind, problem)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pcm)
    tmp.replace(path)
    log.info("%s recorded: %s", kind, path.name)
    return path


def gemini_synth(api_key: str) -> Synth:
    """Gemini text-to-speech: returns 24 kHz 16-bit mono PCM, the rate Jarvis plays at."""
    async def synth(text: str, voice: str) -> bytes:
        from google import genai
        from google.genai import types

        def run() -> bytes:
            client = genai.Client(api_key=api_key)  # keep it referenced: it closes its connection once collected
            reply = client.models.generate_content(
                model=TTS_MODEL, contents=f"Say warmly and briefly: {text}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
            content = reply.candidates[0].content if reply.candidates else None
            if content is None or not content.parts:
                raise RuntimeError("text-to-speech returned no audio")
            return content.parts[0].inline_data.data

        return await asyncio.to_thread(run)

    return synth
