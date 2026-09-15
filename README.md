# Hey Jarvis

**Talk to your Mac. Claude Code does the work.**

Say "Hey Jarvis" and ask for something: fix a bug, check your inbox, open a site, run the tests. Jarvis answers by voice in real time and hands every real action to [Claude Code](https://claude.com/claude-code), which works in the background with access to your projects, terminal, and logged-in Chrome. When the job is done, Jarvis tells you out loud.

- **Hands-free.** Local wake word, then a natural voice conversation you can interrupt.
- **Does real work.** Anything Claude Code can do on your Mac, started by voice and reported back by voice.
- **Speaks your language.** English by default; answer in another language and Jarvis follows you.
- **Cheap.** Gemini Live lists at about $0.005 per minute listening and $0.018 per minute speaking.
- **Asks first.** Pushing to main, deploying, deleting outside the project, sending messages, or paying waits for your spoken "yes".

```
"Hey Jarvis" / ⌃⌥J ─► wake word (local, openWakeWord)
                              │
                              ▼
                  Voice: Gemini Live or OpenAI GPT-Live
                              │  ask_claude · job_status · cancel_job · remember · routines
                              ▼
                  Job manager ─► Claude Code (Agent SDK), one session per project
                              │  guard hook: risky actions wait for a spoken "yes"
                              ▼
                  Reporter ─► voice + macOS notification (+ Telegram when you're away)
```

## Requirements

- macOS (menu bar app, Accessibility, and CoreAudio are macOS-only)
- [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- [Claude Code](https://claude.com/claude-code), installed and logged in. No Anthropic API key is needed.
- A **Gemini API key** ([get one](https://aistudio.google.com/apikey)) or an **OpenAI API key** ([get one](https://platform.openai.com/api-keys))

## Quick start

```bash
git clone https://github.com/dijiclick/hey-jarvis.git
cd hey-jarvis
uv sync
uv run jarvis setup      # voice engine, API key, language, projects folder
uv run jarvis doctor     # checks keys, microphone, Claude Code, wake word
uv run jarvis app        # builds Jarvis.app
```

Double-click **Jarvis.app**. It lives in the menu bar (◎ idle, 🎙 listening, 🔊 speaking, a number while jobs run). The first time, allow **Microphone**, and add Jarvis under **Accessibility** so the hotkey works.

Your keys are saved to `~/.jarvis/.env`, readable only by you. Nothing is stored in this folder.

## Using it

Say **"Hey Jarvis"** (or press ⌃⌥J), wait for the chime, and talk:

- "In storefront, fix the failing login test."
- "What's on my calendar tomorrow?"
- "Open GitHub and tell me which of my pull requests have comments."
- "Every morning at 9, run the tests in storefront and tell me what fails."
- "Remember that I prefer pnpm over npm."
- "What are you working on?" / "Stop that job."

The conversation closes after 20 seconds of silence. Jobs keep running, and Jarvis speaks up again when one finishes.

**Projects** are matched loosely against folders in your projects root (`~/Projects` by default, nested groups included). Add spoken nicknames in `~/.jarvis/projects.json`:

```json
{"the store": "storefront", "books": "~/Projects/ledger-app"}
```

**Memory.** Jarvis keeps what you ask it to remember in `~/.jarvis/profile.md`. Both Jarvis and Claude read it in every conversation, so you only say things once.

**Browser.** To let Claude drive your real, logged-in Chrome, open `chrome://inspect/#remote-debugging` and turn remote debugging on.

**More:**

```bash
uv run jarvis panel        # live panel: running jobs, routines, spend
uv run jarvis routines     # what Jarvis runs on a schedule
uv run jarvis report       # voice minutes and estimated cost
uv run jarvis install      # start at login; `jarvis uninstall` removes it
uv run jarvis run --no-menubar   # run in the terminal instead of the menu bar
```

## Safety

Claude Code runs with full permissions on your Mac, so it can act without clicking through prompts. These actions always pause and ask you by voice first; silence for two minutes counts as no:

- `git push` to main or master, force pushes, `gh pr merge`
- deleting anything outside the job's project folder
- deploys (`vercel --prod`, `fly deploy`, `docker push`, `npm publish`, …)
- sending email or messages (Gmail, Slack, Telegram, …)
- purchases and payments
- writes to non-local databases and production migrations

Only run Jarvis on a Mac and accounts you're comfortable giving an agent this level of access to.

## Configuration

`jarvis setup` writes the essentials. Everything else is optional in `~/.jarvis/.env` (see [`.env.example`](.env.example)):

| Setting | Default | |
|---|---|---|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | | At least one. With both, Gemini is used. |
| `JARVIS_VOICE_PROVIDER` | `gemini` | `gemini` or `openai` |
| `JARVIS_DEFAULT_LANGUAGE` | `English` | The language Jarvis starts every conversation in |
| `JARVIS_PROJECTS_ROOT` | `~/Projects` | Where your projects live |
| `JARVIS_GEMINI_VOICE` | `Enceladus` | Also `Charon`, `Puck`, `Kore`, `Fenrir`, … |
| `JARVIS_VOICE` | `cinder` | OpenAI voice: `cinder`, `stone`, `beacon`, `vesper`, `marin` |
| `JARVIS_HOTKEY` | `<ctrl>+<alt>+j` | |
| `JARVIS_INPUT_DEVICE` | `auto` | `auto` uses the macOS input; or part of a device name, e.g. `macbook` |
| `JARVIS_WAKE_THRESHOLD` | `0.5` | Raise it if Jarvis wakes by mistake |
| `JARVIS_IDLE_CLOSE_S` | `20` | Seconds of silence before the conversation closes |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | | Job reports on Telegram while you're away |

## Troubleshooting

- **It doesn't wake up.** Run `uv run jarvis doctor`. Bluetooth headsets often hand macOS a silent microphone; Jarvis switches away from a silent mic on its own, or set `JARVIS_INPUT_DEVICE=macbook`.
- **The hotkey does nothing.** Add Jarvis.app (or your terminal) under System Settings › Privacy & Security › Accessibility.
- **Logs** are in `~/.jarvis/jarvis.log`.

## Development

```bash
uv run pytest                                  # unit tests
JARVIS_SLOW=1 uv run pytest                    # plus real Claude and wake-model tests
bash tests/e2e/run_e2e.sh                      # real voice runs against a throwaway sandbox
uv run jarvis simulate clip1.wav clip2.wav --model haiku   # drive Jarvis with recorded speech
uv run jarvis ask "run the tests" --project storefront      # Claude side only, from the terminal
```

## License

MIT
