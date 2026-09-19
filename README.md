# Hey Jarvis

**The voice assistant that actually runs your Mac.**

![Hey Jarvis live panel](assets/panel.png)

Say **"Hey Jarvis"** and just talk. Jarvis answers instantly in a natural voice and gets the work done: quick actions happen in about a second, and bigger jobs go to [Claude Code](https://claude.com/claude-code), which works on your browser, apps, files, code and inbox. Keep talking while it works; it tells you when each job is done. Away from your desk? Send it orders from your phone.

## What it can do

- **⚡ Instant actions.** Opens apps and links, types text into any app and presses Enter, presses shortcuts, writes into the Claude chat in VS Code — about a second each, no waiting for an AI agent to think.
- **🌐 Your browser.** Drives your real, logged-in Chrome: searches, clicks, fills forms, books tables, compares flights, sends WhatsApp and Telegram messages on the web, reads any site you're signed in to.
- **💻 Your code.** Builds features, fixes bugs, runs tests, commits and opens pull requests in any of your projects, several at once.
- **📬 Email, calendar, docs.** Reads, drafts and sends email, checks your calendar, searches Drive, through your Claude connectors (Gmail, Google Calendar, Drive, Vercel, …).
- **🖥 Your whole Mac.** Opens and controls any app, runs shell commands and AppleScript, finds and organizes files, changes settings.
- **📱 Orders from your phone.** Message your own private Telegram bot, by text or voice note. Jarvis does the work on your Mac and sends the result back. Only your chat is obeyed.
- **🧠 Memory that lasts.** After every conversation Jarvis keeps the facts worth keeping — how you do things, the people you mention, your preferences — and uses them from then on. Stored on your Mac in a file you can read and edit.
- **🗣 Any language.** English by default. Speak a whole sentence in another language, or ask ("speak Spanish"), and Jarvis switches and stays there; a stray word or a mixed sentence won't flip it.
- **⏰ Routines.** "Every morning at 8:30, brief me on email, calendar and pull requests." Scheduled work that runs on its own and reports back.
- **📊 Live panel.** Running jobs, routines, projects and spend at a glance.
- **✅ You decide how much it does alone.** Pick the autonomy level in the panel or the menu bar, and it applies at once, even to running jobs:
  - **Full auto:** never stops to ask, except before paying.
  - **Balanced** (default): asks before pushing to main, deploying, deleting outside the project, writing to a database, or paying.
  - **Careful:** also asks before any `git push` and before sending email or messages.

  When it asks, a spoken "yes" is all it takes.

## Just say it

- "Hey Jarvis, open Safari." · "Press Cmd+S." · "Type *on my way* in WhatsApp and send it."
- "In storefront, fix the failing checkout test."
- "In the superpower VS Code chat, ask what the tests cover."
- "Send Sam a WhatsApp saying I'll be ten minutes late."
- "Book a table for two on Friday at 8."
- "Find flights to Lisbon next weekend under 200 euros."
- "Every Monday at 9, summarize last week's commits and deploys."
- "Remember that I prefer pnpm over npm."
- "What are you working on?" · "Stop that job."

From your phone, send the same kind of order to your bot as a text or a voice note. `/status` shows what's running and `/cancel` stops it.

## Get started

You need a Mac, [uv](https://docs.astral.sh/uv/) (`brew install uv`), [Claude Code](https://claude.com/claude-code) installed and logged in, and a [Gemini API key](https://aistudio.google.com/apikey) or an [OpenAI API key](https://platform.openai.com/api-keys).

```bash
git clone https://github.com/dijiclick/hey-jarvis.git
cd hey-jarvis
uv sync
uv run jarvis setup      # voice engine, API key, language, projects folder
uv run jarvis doctor     # checks keys, microphone, Claude Code, wake word
uv run jarvis app        # builds Jarvis.app
```

Double-click **Jarvis.app** and say "Hey Jarvis". It lives in your menu bar. The first time, allow **Microphone**, and add Jarvis under **Accessibility** (System Settings › Privacy & Security) so the ⌃⌥J hotkey and instant actions work. For browser control, open `chrome://inspect/#remote-debugging` in Chrome and switch remote debugging on.

### Turn it on and off

| To | Do |
|---|---|
| Turn Jarvis on | Double-click **Jarvis.app** (or run `uv run jarvis run`). ◎ appears in the menu bar and it listens for "Hey Jarvis". |
| Start talking | Say "Hey Jarvis", press ⌃⌥J, or choose **Talk** from the menu bar. |
| End a conversation | Say "bye bye", "turn off", "I don't need you", "خاموش شو", "دیگه کاری ندارم", "görüşürüz" or "выключись" (as the whole sentence: "turn off the Wi-Fi" is still a command). It also hangs up after 20 seconds of silence (`JARVIS_IDLE_CLOSE_S`). |
| Turn Jarvis off | Menu bar ◎ › **Quit**. From a terminal: `pkill -f "jarvis run"`. |
| Start with your Mac | `uv run jarvis install`. Stop that with `uv run jarvis uninstall`. |
| Change how much it does without asking | Menu bar ◎ › **Autonomy**, or the Autonomy switch in the panel. |
| Show the panel | Menu bar ◎ › **Panel**. It brings the open panel forward and opens a new one only if none is open. Set `JARVIS_PANEL_AUTOOPEN=0` if you don't want it to open at start. |

### Orders from your phone (optional)

1. In Telegram, open **@BotFather**, send `/newbot`, pick a name and a username ending in `bot`. BotFather replies with a token.
2. Open your new bot and press **Start**.
3. Find your chat id: open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `message.chat.id`.
4. Add both to `~/.jarvis/.env`:
   ```
   TELEGRAM_BOT_TOKEN=<token>
   TELEGRAM_CHAT_ID=<chat id>
   ```
5. Restart Jarvis. The log says `telegram: listening for orders from the owner's phone`.

Messages from any other chat are ignored and logged, because the bot can drive your whole Mac. Keep the token secret.

## How it works

```
 "Hey Jarvis" / ⌃⌥J            Telegram (text or voice note)
  wake word, on-device                 │ only your chat; voice notes transcribed
          │                            │
          ▼                            ▼
  Real-time voice: Gemini Live ──► Claude Code (Agent SDK), one session per project
  or OpenAI GPT-Live                 shell · AppleScript · any app · files · logged-in Chrome · connectors
          │                                   │
          ├─► instant actions: open app/link,  ▼
          │   type + Enter, shortcuts,      report: spoken, macOS notification,
          │   VS Code chat (~1 s)           or back to Telegram when the order came from there
          │
          └─► long-term memory: facts learned after each conversation (Mem0, stored on this Mac)
```

## Commands

```bash
uv run jarvis setup              # configure voice, key, language, projects folder
uv run jarvis doctor             # check keys, microphone, Claude Code, wake word
uv run jarvis app                # build Jarvis.app (--dest ~/Applications to put it elsewhere)
uv run jarvis run                # start in the menu bar (--no-menubar for the terminal, -v for debug logs)
uv run jarvis panel              # open the live panel
uv run jarvis routines           # list scheduled routines
uv run jarvis report             # voice minutes and cost
uv run jarvis ask "run the tests" --project storefront   # one Claude job from the terminal
uv run jarvis install            # start at login (`jarvis uninstall` removes it)
uv run jarvis simulate a.wav b.wav                     # drive Jarvis with recorded speech (development)
```

## Configuration

`jarvis setup` writes `~/.jarvis/.env` for you. Everything else is optional (see [`.env.example`](.env.example)):

| Setting | Default | |
|---|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | | At least one. With both, Gemini is used. |
| `JARVIS_VOICE_PROVIDER` | `gemini` | `gemini` or `openai` |
| `JARVIS_DEFAULT_LANGUAGE` | `English` | The language every conversation starts in |
| `JARVIS_PROJECTS_ROOT` | `~/Projects` | Where your projects live |
| `JARVIS_GEMINI_VOICE` | `Enceladus` | Also `Charon`, `Puck`, `Kore`, `Fenrir`, … |
| `JARVIS_GEMINI_MODEL` | `gemini-2.5-flash-native-audio-latest` | The Gemini Live model |
| `JARVIS_VOICE` | `cinder` | OpenAI voice: `cinder`, `stone`, `beacon`, `vesper`, `marin` |
| `JARVIS_CLAUDE_MODEL` | `sonnet` | Model for Claude Code jobs |
| `JARVIS_CLAUDE_EFFORT` | `low` | Claude Code effort; `low` keeps spoken requests fast |
| `JARVIS_AUTONOMY` | `balanced` | Starting autonomy level: `full`, `balanced` or `careful`. A switch in the panel or menu bar is saved and wins |
| `JARVIS_HOTKEY` | `<ctrl>+<alt>+j` | |
| `JARVIS_INPUT_DEVICE` | `auto` | `auto` uses the macOS input; or part of a device name, e.g. `macbook` |
| `JARVIS_WAKE_THRESHOLD` | `0.5` | Raise it if Jarvis wakes by mistake |
| `JARVIS_IDLE_CLOSE_S` | `20` | Seconds of silence before a conversation closes |
| `JARVIS_AWAY_AFTER_S` | `600` | After this long without hearing you, reports also go to Telegram |
| `JARVIS_CONFIRM_TIMEOUT_S` | `120` | How long a spoken "yes?" waits; silence counts as no |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | | Orders from your phone, and reports while you're away |
| `OPENAI_ADMIN_KEY` | | Real OpenAI spend in `jarvis report` and the panel |
| `JARVIS_HOME` | `~/.jarvis` | Where settings, memory and logs live |
| `JARVIS_PANEL_PORT` | `8787` | Port of the live panel |
| `JARVIS_PANEL_AUTOOPEN` | `1` | `0` stops the panel opening at start |

### What lives in `~/.jarvis`

| File | |
|---|---|
| `.env` | Your keys and settings, readable only by you |
| `memories.md` | Facts Jarvis learned from past conversations; edit or delete lines freely |
| `profile.md` | Facts you asked it to remember ("remember that …") |
| `projects.json` | Spoken nicknames for projects, e.g. `{"the store": "storefront"}` |
| `memory/` | The local memory store behind `memories.md` |
| `jarvis.log` | What Jarvis heard, said and did, including every instant action and its result |
| `jarvis.db` | Jobs, routines and transcripts |

## Cost and privacy

- **Voice** runs about 1–2¢ a minute on Gemini Live, only while a conversation is open. OpenAI's voice is about 5¢ a minute.
- **Memory and voice-note transcription** use Gemini too, a fraction of a cent each time.
- **Claude Code** runs on your existing Claude subscription.
- Your voice goes to the voice engine you chose while a conversation is open; the wake word is detected on your Mac. Memory is stored on your Mac, and the memory library's telemetry is switched off.

## Troubleshooting

- **It doesn't wake up.** Run `uv run jarvis doctor`. Bluetooth headsets sometimes give macOS a silent mic; Jarvis switches away on its own, or set `JARVIS_INPUT_DEVICE=macbook`.
- **The hotkey or instant actions do nothing.** Add Jarvis.app under System Settings › Privacy & Security › Accessibility.
- **"Write it in the VS Code chat" says it couldn't confirm.** The message was typed and sent; if Claude in VS Code is busy, it queues the message and picks it up when it finishes.
- **The Telegram bot doesn't answer.** Check the log for `telegram: listening`, that you pressed **Start** in the bot, and that `TELEGRAM_CHAT_ID` is your chat.
- **Jarvis said it's on it but nothing happened.** Jarvis notices this itself and starts the task anyway; each case is logged as `missed action` in the log.
- **Logs:** `~/.jarvis/jarvis.log`.

## Development

```bash
uv run pytest                                  # unit tests (a few seconds)
JARVIS_SLOW=1 uv run pytest                    # plus real Claude and wake-model tests
bash tests/e2e/run_e2e.sh                      # real voice runs in a throwaway sandbox
```

See [`CLAUDE.md`](CLAUDE.md) for how the code is organized and how to test changes safely.

## License

MIT
