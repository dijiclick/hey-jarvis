# Security

Jarvis can drive your whole Mac: it runs shell commands, controls apps, and uses your logged-in browser through Claude Code. Please treat security issues seriously and report them privately.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the **Security** tab of this repository and choose **Report a vulnerability**. Please don't open a public issue for security problems.

Include what you found, how to reproduce it, and what an attacker could do with it. You'll get a reply within a week.

## What's in scope

- Anything that lets someone other than the owner make Jarvis act: the Telegram bot accepting another chat, the local panel accepting requests from other websites, spoken or typed input that bypasses the autonomy level.
- Leaks of keys or personal data from `~/.jarvis` (`.env`, memories, logs, the database).
- Claude Code actions that should pause for a spoken yes at the current autonomy level but don't.

## How Jarvis protects you

- API keys live only in `~/.jarvis/.env` (mode 600) and are never logged in full.
- The Telegram bot obeys only the owner's chat id.
- The live panel listens on `127.0.0.1` only and accepts changes only from its own page.
- Risky actions (push to main, deploy, delete outside the project, database writes, paying) pause for a spoken yes, depending on the autonomy level you choose.
