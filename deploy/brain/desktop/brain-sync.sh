#!/usr/bin/env bash
# Desktop -> middo247 sync of the Claude config the brain depends on, plus a pull of
# the walk journal. Stopgap until Syncthing is set up. Safe to run on a timer:
# --update never overwrites a newer file on the receiving side.
set -u
H="$HOME"; S="server"
timeout 60 rsync -aq --update "$H/.claude/skills/"  "$S:$H/.claude/skills/"  2>/dev/null || true
timeout 60 rsync -aq --update "$H/.claude/agents/"  "$S:$H/.claude/agents/"  2>/dev/null || true
timeout 20 rsync -aq --update "$H/.claude/CLAUDE.md" "$S:$H/.claude/CLAUDE.md" 2>/dev/null || true
MEM="$H/.claude/projects/-home-markmiddo-dev-eventflo/memory"
timeout 60 rsync -aq --update "$MEM/" "$S:$MEM/" 2>/dev/null || true
timeout 60 rsync -aq --update "$S:$MEM/" "$MEM/" 2>/dev/null || true
# personal task inbox (script + data), both ways, newest file wins
mkdir -p "$H/.claude/tasks"
timeout 20 rsync -aq --update "$H/.claude/tasks/" "$S:$H/.claude/tasks/" 2>/dev/null || true
timeout 20 rsync -aq --update "$S:$H/.claude/tasks/" "$H/.claude/tasks/" 2>/dev/null || true
