#!/usr/bin/env bash
# SessionStart hook for the desktop Claude Code: pull today's walk journal from
# middo247 and print it so the session knows what Mark and Synthia already covered.
# Install: copy to ~/.claude/hooks/ and register under hooks.SessionStart in
# ~/.claude/settings.json. Silent when the server is unreachable or nothing exists.
set -u
JOURNAL_DIR="$HOME/.claude/projects/-home-markmiddo-dev-eventflo/memory/walk"
TODAY="$(date +%F)"
mkdir -p "$JOURNAL_DIR"
timeout 8 rsync -aq --update "server:$JOURNAL_DIR/" "$JOURNAL_DIR/" 2>/dev/null || true
FILE="$JOURNAL_DIR/$TODAY.md"
if [ -s "$FILE" ]; then
  echo "WALK JOURNAL for today (Mark talked to Synthia on the walk; already done — do not redo):"
  tail -n 60 "$FILE"
fi
