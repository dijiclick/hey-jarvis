import asyncio
import logging

import aiohttp

log = logging.getLogger("jarvis.notifier")


def applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Notifier:
    def __init__(self, http: aiohttp.ClientSession | None, bot_token: str | None, chat_id: str | None):
        self.http = http
        self.bot_token = bot_token
        self.chat_id = chat_id

    async def desktop(self, title: str, body: str) -> None:
        script = f"display notification {applescript_string(body[:220])} with title {applescript_string(title)}"
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()

    async def telegram(self, text: str) -> bool:
        if not (self.http and self.bot_token and self.chat_id):
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with self.http.post(url, json={"chat_id": self.chat_id, "text": text[:4000]}) as resp:
            if resp.status != 200:
                log.warning("telegram send failed with HTTP %s", resp.status)
            return resp.status == 200
