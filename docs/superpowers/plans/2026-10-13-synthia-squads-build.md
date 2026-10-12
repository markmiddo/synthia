# Synthia Squads: Build Plan (phases 0 "Act", 1 engine, 2 Growth squad v1)

**Date:** 2026-10-13
**High-level plan:** `docs/superpowers/plans/2026-10-13-synthia-squads-high-level.md`
**Base:** branch `feat/squads` off `feat/jarvis-see` (PR #28, not merged yet). PR targets `feat/jarvis-see`
until #28 merges, then `development`.

## Decisions taken (Mark, "let's build this", 2026-10-13)

1. **First job:** a week of blog posts (three posts) drafted against the dev blog.
2. **Alongside, not replacing,** the eva-core Autopilot writer. Squad posts are better-researched
   extras; the Autopilot keeps its Mon/Wed/Fri drafts.
3. **Non-blog output** (phase 3) lands as ActiveCampaign drafts plus a Drive handoff for Corey's team.

## Not in this build

- Merging #28, murmur#6 or eva-core#182. Switching the Autopilot on (#3108).
- Pushing squad drafts into eva-core. #182 has no enqueue API yet (only an in-process
  `Store.EnqueueContentItem`). Squads write the Autopilot's exact `blog.Payload` JSON into the job's
  `out/` folder. An eva-core follow-up adds an `autopilot_enqueue` MCP tool; then a `deliver` step
  posts it. Until then Mark approves from the desk folder.
- Hard-stop changes to the permission gate (phase 3 "Run").

## Shared contract: the squad registry

All three parts meet in one JSON file, written only by the Python squad engine:

`~/.local/share/synthia/squads/registry.json`

```json
{
  "version": 1,
  "members": {
    "<pane_id>": {
      "agent_name": "growth-writer-1",
      "squad": "growth",
      "job": "2026-10-13-week-of-posts",
      "role": "growth-writer",
      "title": "Writer",
      "parent": "<pane_id of the director, or null for a director>",
      "opened_by": "synthia",
      "started_at": "2026-10-13T09:12:00+11:00",
      "ended_at": null
    }
  }
}
```

Writes are atomic (temp file plus `os.replace`) under an `fcntl` lock on `registry.lock`. Members
whose pane is gone from `herdr agent list` are marked `ended_at` on the next write.

## Part A: Python, "Act" herdr tools and the squad engine

### A1. `src/synthia/herdr.py`: thin herdr CLI wrapper

Synchronous functions using `subprocess.run([...], timeout=...)`, never `shell=True`. Each parses the
JSON result and raises `HerdrError` with herdr's message on failure.

- `agent_list()`, `agent_read(target, lines)`, `agent_wait(target, timeout_ms)`,
  `agent_prompt(target, text, wait=False, timeout_ms=None)`
- `ensure_workspace(label)`: find a workspace by label in `workspace list`, else
  `workspace create` with that label; returns its root pane id. Squads live in a workspace named
  `squads` so they never crowd Mark's own tabs.
- `split(pane_id, direction, cwd)`: `pane split --pane X --direction D --cwd C --no-focus`;
  returns the new pane id. Pick `right` while the tab has fewer than three columns, else `down`
  (use `pane layout`).
- `start_claude(name, pane_id, model, agent)`: `agent start <name> --kind claude --pane <id> --
  --model <model> --agent <agent> --permission-mode bypassPermissions`.
- `close_pane(pane_id)`, `rename(pane_id, title)` (via `pane report-metadata --source synthia --title`).

Probe the real CLI (`herdr agent`, `herdr pane`, `herdr workspace` group help) before coding; the
installed binary is the authority. Agent names must match `[a-z][a-z0-9_-]{0,31}`.

### A2. `src/synthia/squads/`: the engine

- `model.py`: `Squad` and `Role` dataclasses, loaded from YAML. A squad file
  `~/.config/synthia/squads/<id>.yaml`:

  ```yaml
  id: growth
  name: Growth
  director: growth-director
  cap: 4                 # live specialists at once, director not counted
  cwd: ~/dev/eventflo
  roles:
    growth-director:    {title: Marketing Director, model: claude-opus-5-5, hires: [growth-seo, growth-writer, growth-editor, growth-designer]}
    growth-seo:         {title: SEO Strategist, model: claude-sonnet-5-5}
    growth-writer:      {title: Writer, model: claude-sonnet-5-5}
    growth-editor:      {title: Editor and Fact-checker, model: claude-sonnet-5-5}
    growth-designer:    {title: Designer, model: claude-sonnet-5-5}
  ```

  Each role's prompt is the Claude Code agent file `~/.claude/agents/<role>.md`.
- `registry.py`: the shared contract above (load, add, end, live members of a job, prune).
- `desk.py`: a job folder per job at `~/.local/share/synthia/squads/<squad>/jobs/<job>/`:
  `brief.md` (from Mark or Synthia), `status.json` (`state`: briefed, working, review, done,
  stopped; `log`: list of `{at, who, text}`), `work/<role>/` for each specialist, `out/` for
  finished deliverables. Job id is `YYYY-MM-DD-<slug>`.
- `engine.py`:
  - `start_job(squad_id, brief, slug)`: makes the desk, opens the director pane in the `squads`
    workspace, names it `<squad>-director`, registers it, and prompts it with the brief plus the desk
    path and the hire command.
  - `hire(job_path, role, brief, parent_pane)`: refuses if `role` is not in the parent's `hires`, or
    if the job already has `cap` live specialists. Opens a pane next to the parent, starts Claude with
    the role's model and agent file, registers it, prompts it with the brief plus its `work/<role>/`
    folder. Returns the agent name.
  - `ask(name, text)`, `read(name, lines)`, `wait(name, timeout_s)`: thin passes to herdr, only for
    members of this job.
  - `dismiss(name)`: closes the pane, ends the registry entry. Only panes in the registry.
  - `stop_job(job)`: dismisses every live member, director last, state `stopped`.
- `cli.py`: console script `synthia-squad` (add to `pyproject.toml`). The director drives the team
  with it from its own pane, so every command reads `HERDR_PANE_ID` to know the caller:
  `synthia-squad hire <role> "<brief>"`, `ask <name> "<text>"`, `read <name> [--lines N]`,
  `wait <name> [--timeout S]`, `dismiss <name>`, `log "<text>"`, `deliver <file>` (copy into
  `out/`, append to the log), `done` (state review, ping Synthia). Plus for Mark and Synthia:
  `start <squad> "<brief>" [--slug S]`, `status [<job>]`, `stop <job>`, `install <squad>` (copy the
  repo's `squads/<squad>/` agent files into `~/.claude/agents/` and the yaml into
  `~/.config/synthia/squads/`, never overwriting a file that differs without `--force`).
  The caller's job is found from the registry entry for `HERDR_PANE_ID`.
- **Done signal:** `done` writes `state: review` and appends a line to
  `~/.local/share/synthia/squads/events.jsonl`. The brain tails that file (A3) and tells Mark.

### A3. Brain tools: `src/synthia/brain/herdr_tools.py`

In-process MCP server `herdr`, registered next to `jobs` in `concierge.py` and treated as the brain's
own server in `gate.py` (no spoken confirm):

- `fleet()`: compact list of live agents (name, title, repo, state, squad role if any).
- `open_agent(name, cwd, prompt, model?)`: Synthia opens a plain Claude agent in the `squads`
  workspace and registers it with `squad: null`, `opened_by: synthia`.
- `prompt_agent(name, text)`, `read_agent(name, lines)`, `close_agent(name)`. `close_agent` only
  closes panes in the registry (opened by Synthia); anything else returns a refusal she reads out.
- `start_squad(squad, brief, slug?)`, `squad_status(job?)`, `stop_squad(job)`.

`serve.py` tails `events.jsonl` (poll every 5 s, remember the offset in the state dir) and pushes a
job event ("Growth's week of posts is ready for review") the same way job results are pushed.

Persona addition (short): she can run squads; she briefs the director in one paragraph, never
does the specialists' work herself, and reports outcomes.

### A4. Tests

`tests/test_herdr.py` (fake `subprocess.run`), `tests/test_squads_registry.py`,
`tests/test_squads_engine.py` (fake herdr module: cap enforced, hires list enforced, dismiss only
registered, stop order), `tests/test_squads_cli.py`, `tests/test_herdr_tools.py`. Gates: black,
isort, mypy, pytest.

## Part B: Growth squad v1 content

In the repo at `squads/growth/`: `squad.yaml` (as A2) and `agents/growth-*.md`, Claude Code agent
files with frontmatter `name`, `description`, `model`, `tools`.

Shared rules in every role (the Growth Engine "four ways we zero" plus Mark's rules):

- Drafts only. Never publish, send, post, email or message anyone. Mark is the only approver.
- Every claim about a competitor (fees, features) is fetched fresh and cited with URL and the date
  checked. eventflo's own fee is the placeholder `[[EVENTFLO FEE — Mark/Corey sign-off]]`.
- Real value on every page: real data, a real guide or a true comparison. No thin pages.
- Post as eventflo only. No fake reviews or accounts. Nothing touches checkout.
- Australian English. eventflo house voice (read the Autopilot prompt in eva-core #182
  `autopilot/blog/prompt.go` and lint rules `autopilot/blog/lint.go`; the writer and editor apply the
  same lint).

Roles:

- **growth-director** (Opus): reads the brief, decides the mix (default: three posts, at least two
  fan-side), hires the SEO strategist first, then one writer per post (cap 4 live), the editor and
  the designer. Reviews every draft against the rules and sends work back with specific notes.
  Delivers only what passes. Writes `out/summary.md` for Mark (what, why, target query, search
  volume, what needs his eye) and calls `synthia-squad done`.
- **growth-seo** (Sonnet): uses the `seo-*` skills and DataForSEO (credentials on middo247; reach
  them the way the seo skills do) to produce one brief per post in `work/growth-seo/`: target query,
  volume, difficulty, intent, competing pages, outline, FAQ questions, internal links. Fan-side terms
  first (festival resale, "bush doof"). Never repeats a topic in the Autopilot `topics.go` list or an
  existing `/blog` post.
- **growth-writer** (Sonnet): turns one brief into the exact `blog.Payload` JSON (title, slug,
  excerpt, body markdown, tags, faq, coverImageUrl empty, coverImageAlt, coverImageBrief,
  targetQuery, warnings, digestNote), applying the lint rules.
- **growth-editor** (Sonnet): adversarial. Re-fetches every competitor claim and cites it, cuts
  fluff, checks lint, checks no claim lacks a source. Returns pass or a numbered fix list.
- **growth-designer** (Sonnet): turns `coverImageBrief` into a cover with the `nano-banana-pro`
  skill (16:9, no text in image, eventflo palette), saves it next to the payload, fills
  `coverImageAlt`.

Output per post: `out/<slug>.json` (Payload) and `out/<slug>.png`.

## Part C: HUD (Rust and React)

- `fleet.rs`: read `registry.json` (missing file is fine) and attach `squad`, `job`, `role`,
  `title` and `parent` to matching fleet agents by pane id. Parent links nest specialists under their
  director in the constellation (a squad renders as a cluster: director node, specialists orbiting it,
  labelled with the squad name).
- New command `squads_list()`: reads `~/.config/synthia/squads/*.yaml` plus each role's agent file
  frontmatter (`description`, `model`), and the jobs under the desk with their `status.json`.
- New command `squad_role_save(squad, role, fields)`: edits title, model and hires in the yaml (use
  the comment-preserving writer if it fits, else serde_yaml round trip) and the agent file body.
- **Company view:** a second view toggled from the drag bar (Constellation, Company). Shows each squad
  as an org chart (director at top, roles beneath, model chip, "hires" links), live members lit, and
  recent jobs with state and a link to open the job folder. Click a role to edit its title, model and
  prompt in a side panel. Same tokens and fonts as the constellation; legible, no space-age fonts.
- Tests: registry merge into fleet, squads yaml parse. Clippy clean, `cargo test --lib`, `npm run
  tauri build -- --no-bundle`.

## Verify (orchestrator, with Mark)

1. `synthia-squad install growth`.
2. Ask Synthia "get marketing on this week's posts". She calls `start_squad`; a `squads` workspace
   appears with the director; the director hires the SEO strategist; the HUD shows the cluster.
3. Cap holds at four live specialists.
4. Job ends in `review` with three Payload JSON files, covers and `summary.md`. Synthia says it is
   ready.
5. Nothing was published or sent anywhere.
