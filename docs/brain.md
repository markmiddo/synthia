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

The systemd units use `%h` for the home directory, so the repo must live at `~/dev/misc/synthia`
and the venv at `~/dev/misc/synthia/venv`.

`install.sh` will not start the service while `brain.env` still holds the placeholder token; it
prints the two edit steps and exits, so re-run it once the token and allowed user id are real.

It also copies `deploy/brain/security-policy.yaml` to `~/.config/synthia/security/policy.yaml`
(only if that file does not already exist). On a headless server the security-gate hook would
otherwise wait thirty seconds for a GUI answer to every HIGH-severity hit and then deny anyway;
the policy denies HIGH and CRITICAL outright instead. Voice confirmation is unaffected — git push,
PR merges, service restarts and connector mutations are brain gate rules, not security_gate rules.

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
- Background workers run headless, so nobody can answer a permission prompt for them. They get
  their own allowlist (`worker_allowed_tools` in `brain.yaml`: Bash, the file tools, Skill, Task
  and the connector servers) — wider than the concierge's read-only one. What actually stops a
  dangerous worker call is the synced PreToolUse security-gate hook. Code-changing jobs go through
  `/build`, which works in its own worktree.
- Job records and worker logs older than fourteen days are pruned at startup.

## Troubleshooting

    journalctl --user -u synthia-brain -f          # live log
    ls ~/.local/share/synthia/brain/jobs/           # job records and worker logs
    cat ~/.local/share/synthia/brain/session.json   # current session id and date

"Cloud speech is down": Google credentials missing or expired in `brain.env`.
No replies at all: check `telegram_allowed_users` matches your Telegram user id.
Worker fails instantly: run `claude -p "hi" --output-format json` in `~/dev/eventflo` on the server.

## Walk journal (continuity with the desktop)

Every turn, dispatched job, job result and confirmation decision is appended to
`~/.claude/projects/-home-markmiddo-dev-eventflo/memory/walk/YYYY-MM-DD.md` on the server
(`journal_dir` in `brain.yaml`). The desktop reads it two ways:

- `deploy/brain/desktop/walk-journal-session-hook.sh` — install to `~/.claude/hooks/` and register
  under `hooks.SessionStart` in `~/.claude/settings.json`; it pulls today's file from the server and
  prints it into the new session's context.
- The `/morning` skill checks today's journal first and recaps instead of re-running when the
  briefing already happened on the walk.

`deploy/brain/desktop/brain-sync.{sh,service,timer}` push skills, agents, global instructions and the
eventflo memory folder to the server every 10 minutes and pull the memory folder back (stopgap until
Syncthing). Install: copy the script to `~/.claude/hooks/`, the units to `~/.config/systemd/user/`,
then `systemctl --user enable --now brain-sync.timer`.

## Reminders from the walk

"Remind me to X" on the walk becomes a `note` item in the personal inbox (`~/.claude/tasks/inbox.py add note`).
The inbox script and its JSON are synced both ways by `brain-sync.timer`, and the SessionStart hook pulls
`inbox.json` and lists open notes, so a reminder set by voice shows up in the next desktop session and
can be ticked off from either side.
