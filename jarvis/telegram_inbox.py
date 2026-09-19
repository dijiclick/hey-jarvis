"""Orders from the owner's phone: a private Telegram bot that Jarvis reads and answers.

Only the owner's chat is obeyed, because the bot drives the whole Mac. Messages from before Jarvis started are
skipped so a backlog never replays as fresh orders. Voice notes are transcribed first, and the reply says what was
heard, so a mishearing shows before it matters.
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

log = logging.getLogger("jarvis.telegram")

API = "https://api.telegram.org"
# measured on real Persian clips: flash-lite turned "جارویس، ساعت چنده؟" into "Joe Arviza, so ATChande." (and into
# Cyrillic once told the language); flash with a Persian hint transcribed every clip correctly, in 2-5 s
TRANSCRIBE_MODEL = "gemini-3.5-flash"
TRANSCRIBE_PROMPT = (
    "Transcribe this voice message word for word. The speaker is Iranian: most messages are in Persian (Farsi, as "
    "spoken in Iran), some in English, and they often mix English words into Persian. Write Persian in Persian script. "
    "Keep English words, app names, product names and file names in English letters exactly as said (for example "
    "WhatsApp, VS Code, salam.txt). Never translate, never romanize, and never output Hindi, Urdu or Arabic. "
    "Reply with only the words.")
POLL_TIMEOUT_S = 25


class TelegramInbox:
    def __init__(self, *, fetch: Callable[[int | None], Awaitable[list[dict]]], send: Callable[[str], Awaitable[Any]],
                 download: Callable[[str], Awaitable[bytes]], transcribe: Callable[[bytes], Awaitable[str]],
                 order: Callable[[str], int], status: Callable[[], str], cancel: Callable[[], Awaitable[str]],
                 owner_chat_id: str, started_at: float | None = None):
        self.fetch, self.send, self.download, self.transcribe = fetch, send, download, transcribe
        self.order, self.status, self.cancel = order, status, cancel
        self.owner_chat_id = str(owner_chat_id)
        self.started_at = time.time() if started_at is None else started_at
        self.offset: int | None = None
        self.failures = 0

    async def poll_once(self) -> None:
        try:
            updates = await self.fetch(self.offset)
        except Exception as e:
            self.failures += 1
            log.warning("telegram: could not read messages (%s)", type(e).__name__)
            return
        self.failures = 0
        for update in updates:
            self.offset = max(self.offset or 0, update["update_id"] + 1)
            try:
                await self._handle(update.get("message") or {})
            except Exception:
                log.exception("telegram: could not handle a message")

    async def _handle(self, message: dict) -> None:
        if not message:
            return
        chat = str((message.get("chat") or {}).get("id", ""))
        if chat != self.owner_chat_id:
            log.warning("telegram: ignored a message from chat %s; only the owner can give orders", chat)
            return
        if message.get("date", 0) < self.started_at:
            return
        text, heard = (message.get("text") or "").strip(), False
        if not text and message.get("voice"):
            text = (await self.transcribe(await self.download(message["voice"]["file_id"]))).strip()
            heard = True
        if not text:
            return
        command = text.split()[0].lower()
        if command in ("/start", "/help"):
            await self.send("Jarvis here. Send me an order by text or voice note; /status shows what's running, "
                            "/cancel stops it.")
        elif command == "/status":
            await self.send(self.status())
        elif command == "/cancel":
            await self.send(await self.cancel())
        else:
            job = self.order(text)
            log.info("telegram: order from the owner started job %s", job)
            prefix = f"Heard: “{text}”\n" if heard else ""
            await self.send(f"{prefix}On it (job {job}). I'll send the result here.")

    async def run(self, stop: asyncio.Event) -> None:
        log.info("telegram: listening for orders from the owner's phone")
        while not stop.is_set():
            await self.poll_once()
            if self.failures:
                await asyncio.sleep(min(60, 2 ** self.failures))


class TelegramBot:
    """The real Telegram side: long polling and voice-note downloads for one bot token."""

    def __init__(self, http: aiohttp.ClientSession, token: str):
        self.http = http
        self.token = token

    async def fetch(self, offset: int | None) -> list[dict]:
        params: dict[str, Any] = {"timeout": POLL_TIMEOUT_S, "allowed_updates": '["message"]'}
        if offset is not None:
            params["offset"] = offset
        timeout = aiohttp.ClientTimeout(total=POLL_TIMEOUT_S + 15)
        async with self.http.get(f"{API}/bot{self.token}/getUpdates", params=params, timeout=timeout) as resp:
            data = await resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "getUpdates failed"))
        return data["result"]

    async def download(self, file_id: str) -> bytes:
        async with self.http.get(f"{API}/bot{self.token}/getFile", params={"file_id": file_id}) as resp:
            path = (await resp.json())["result"]["file_path"]
        async with self.http.get(f"{API}/file/bot{self.token}/{path}") as resp:
            return await resp.read()


def _gemini_client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


async def transcribe_with_gemini(api_key: str | None, audio: bytes, client_factory=_gemini_client) -> str:
    """Turn a Telegram voice note (OGG/Opus) into text in the language it was spoken."""
    if not api_key:
        return ""
    from google.genai import types

    def run() -> str:
        client = client_factory(api_key)  # keep it referenced: the client closes its connection once collected
        reply = client.models.generate_content(
            model=TRANSCRIBE_MODEL,
            contents=[types.Part.from_bytes(data=audio, mime_type="audio/ogg"), TRANSCRIBE_PROMPT])
        return (reply.text or "").strip()

    return await asyncio.to_thread(run)
