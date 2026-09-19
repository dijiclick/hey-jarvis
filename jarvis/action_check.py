"""Catches the voice model saying it will do something without calling a tool.

The Gemini voice model sometimes answers "I'm opening Trendyol and giving it to Claude Code" and then does nothing.
After such a reply, a small text model reads the exchange and says whether an action was promised, and if so, what
the user wanted done, in English, so the system can start it for real.
"""
import asyncio
import json
import logging

log = logging.getLogger("jarvis.action_check")

CHECK_MODEL = "gemini-3.5-flash-lite"
CHECK_PROMPT = """A voice assistant that controls the user's Mac replied to the user. It can only act by calling a
tool, and it called none this time. Decide whether its reply promised or claimed an action: opening, searching,
finding, sending, writing, checking, buying, or handing the work to Claude Code. Answering a question, chatting,
asking which one the user means, or saying it can't do something is not an action.

User said: {user}
Assistant replied: {assistant}

Reply with JSON only: {{"promised_action": true or false, "task": "<if true, what the user wants done, as one
clear instruction in English, keeping names, sites and messages exactly as said>"}}"""


def _gemini_client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


async def promised_action(api_key: str | None, user: str, assistant: str, client_factory=_gemini_client) -> str | None:
    """The task the assistant promised but didn't start, or None when it only talked."""
    if not api_key:
        return None
    from google.genai import types

    def run() -> str | None:
        client = client_factory(api_key)  # keep it referenced: the client closes its connection once collected
        reply = client.models.generate_content(
            model=CHECK_MODEL, contents=CHECK_PROMPT.format(user=user, assistant=assistant),
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
        try:
            verdict = json.loads(reply.text or "")
        except ValueError:
            log.warning("action check: unreadable verdict %r", (reply.text or "")[:80])
            return None
        task = str(verdict.get("task") or "").strip()
        return task if verdict.get("promised_action") and task else None

    return await asyncio.to_thread(run)
