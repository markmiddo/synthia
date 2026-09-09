# Synthia Brain (mobile voice)

The brain is a long-lived Claude Agent SDK session running in `~/dev/eventflo` on middo247,
talking to Mark over Telegram voice notes. Design: `docs/superpowers/specs/2026-09-09-mobile-voice-brain-design.md`.

## Authentication

Runs on the Claude Max login already used by the `claude` CLI on the server; no `ANTHROPIC_API_KEY` is needed. Verified 2026-09-09 with `scripts/brain_auth_spike.py`: both runs succeeded with and without the API key variable, model reported `claude-fable-5-1`. The `total_cost_usd` and `model_usage` fields the SDK reports are list-price equivalents shown under a Max plan, not billing.

## Install on middo247

    git clone git@github.com:markmiddo/synthia.git ~/dev/misc/synthia   # once
    cd ~/dev/misc/synthia && git pull && deploy/brain/install.sh
    nano ~/.config/synthia/brain.env     # bot token, Google credentials path
    nano ~/.config/synthia/brain.yaml    # allowed user id, chat id, repos
    systemctl --user restart synthia-brain

Prerequisites on the server: `claude` CLI logged in (`claude login`), eventflo repos cloned under
`~/dev/eventflo`, Syncthing folders shared per `deploy/brain/syncthing-folders.md` (this also brings
`~/.claude/settings.json` with the security-gate PreToolUse hook that workers rely on), and `ffmpeg`
installed (`sudo apt install ffmpeg`).

## Run from the desktop (text only)

    synthia-brain repl -v

Drive the same brain from the keyboard. `/stop`, `/new`, `/jobs`, `/quit`.

## Telegram commands

`/stop` interrupts the current reply. `/new` starts a fresh session (handover is not carried).
`/jobs` lists background jobs. Anything else, voice or text, goes to the brain.

A risky action is read out as a voice note ending in 'Say yes to confirm'; reply yes, yep, confirm or go ahead within two minutes, anything else denies.

## How it behaves

- Quick things are answered inline. Long things ("run the morning ritual") are dispatched as
  background workers; you get a voice note when they finish.
- Risky tool calls (git push, PR merge, service restarts, database writes) are read out and need a
  spoken "yes" within two minutes, otherwise denied.
- A new session starts each day with a five-line handover from the previous one.

## Troubleshooting

    journalctl --user -u synthia-brain -f          # live log
    ls ~/.local/share/synthia/brain/jobs/           # job records and worker logs
    cat ~/.local/share/synthia/brain/session.json   # current session id and date

"Cloud speech is down": Google credentials missing or expired in `brain.env`.
No replies at all: check `telegram_allowed_users` matches your Telegram user id.
Worker fails instantly: run `claude -p "hi" --output-format json` in `~/dev/eventflo` on the server.
