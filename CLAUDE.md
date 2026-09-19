# Working on Hey Jarvis

A macOS voice assistant: a local wake word opens a real-time voice session (Gemini Live or OpenAI GPT-Live); quick
actions run directly on the Mac, and real work is delegated to Claude Code through the Agent SDK.

## Where things are

| Module | Does |
|---|---|
| `jarvis/app.py` | Wires everything together and runs the background tasks (panel, routines, microphone checks, Telegram listener) |
| `jarvis/voice.py` | Voice session, the voice model's prompt and tools, language stickiness, conversation turns |
| `jarvis/mac_actions.py` | The fast lane: open app/link, paste + Enter, shortcuts, VS Code chat. Checks the target app is in front before typing |
| `jarvis/worker.py` | One Claude Code session per project: model/effort, system prompt, session reuse cap |
| `jarvis/jobs.py` | Job queue and events; `reporter.py` turns results into speech and notifications |
| `jarvis/guard.py` | Which Claude actions pause for a spoken yes, per autonomy level (full / balanced / careful) |
| `jarvis/autonomy.py` | The current autonomy level, saved in `~/.jarvis/autonomy.json`; switched from the panel and menu bar |
| `jarvis/memory.py` | Long-term memory (Mem0 + Gemini, stored locally); writes `~/.jarvis/memories.md` |
| `jarvis/profile.py` | Builds the "what you know about the user" blocks for the voice and for Claude |
| `jarvis/telegram_inbox.py` | Orders from the owner's phone; voice-note transcription |
| `jarvis/action_check.py` | Catches the voice model promising an action without calling a tool; the voice then starts it as a Claude job |
| `jarvis/speech_text.py` | Spoken-text cleanup, language detection, goodbye detection |
| `jarvis/config.py` | Every setting, read from `~/.jarvis/.env` and the environment |
| `jarvis/cli.py` | `jarvis setup / doctor / run / ask / app / install / …` |

## Changing code

- Test first: write the failing test, watch it fail for the right reason, then fix. `uv run pytest -q` runs the whole
  suite in a few seconds; keep it green.
- Tests use fakes for the shell, Telegram, Mem0 and Gemini. Make fakes behave like the real thing where it matters
  (the Gemini client, for example, closes its connection when it's garbage-collected).
- Behavior that only shows up on a real Mac needs a live check too: several bugs here passed every unit test (plugins
  registered off the main thread, Cmd+Esc toggling the Claude chat's focus away, a transcription model that couldn't
  handle short non-English clips). Measure with real audio, real apps, or the real log before calling something fixed.
- New settings go in `config.py`, `.env.example` and the README's configuration table together.

## Testing live, safely

- The fast lane types into whatever app is in front. Always pass the target `app`, and never type while unsure what's in
  front: a test once sent its text into the VS Code chat instead of TextEdit.
- `vscode_chat` sends into the active Claude Code chat in VS Code. If that's the chat you're working in, the test
  message arrives there as a user message; mark test messages clearly.
- macOS automation prompts ("… wants to control …") block AppleScript until someone answers them. Prefer `open -a` and
  System Events over `tell application "<app>"`.
- `grep "missed action" ~/.jarvis/jarvis.log` lists every time the voice model said it would act but called no tool,
  with what the user said; use it to find prompt or model problems.
- Restart the app after changing code: quit it from the menu bar (or kill the `jarvis run` process), then
  `open Jarvis.app`. The log is `~/.jarvis/jarvis.log`; every fast-lane action is logged with its result.

## Secrets and personal data

- Keys live only in `~/.jarvis/.env` (mode 600). Never print a key in full, never commit `.env`, `jarvis.db`, logs,
  `memories.md` or `profile.md`.
- Tests and docs use neutral example names and places, never real contacts, projects or paths.
