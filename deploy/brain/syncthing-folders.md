# Syncthing folders: desktop <-> middo247

Install `syncthing` on both machines (`sudo apt install syncthing`, `systemctl --user enable --now syncthing`).
Pair the devices in the web UI (http://localhost:8384) once. Then share these folders, both directions,
same path on both machines:

| Folder ID | Path |
|-----------|------|
| claude-skills | ~/.claude/skills |
| claude-agents | ~/.claude/agents |
| claude-plugins | ~/.claude/plugins |
| claude-eventflo-memory | ~/.claude/projects/-home-markmiddo-dev-eventflo/memory |
| claude-root-files | ~/.claude (see ignore list below; only settings.json and CLAUDE.md pass) |

`.stignore` for `claude-root-files`:

    !settings.json
    !CLAUDE.md
    *

Never sync: `~/.claude/projects/*/` transcripts, `.credentials.json`, `statsig`, caches, `*.bak*`.
Secrets (`.mcp.json` keys, Google credentials, bot token) are copied by hand into
`~/.config/synthia/brain.env` on the server.
