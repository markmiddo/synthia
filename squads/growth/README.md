# Growth squad

An AI team that drafts eventflo blog posts for Mark to approve. A Marketing Director (Opus) hires four specialists (Sonnet): an SEO Strategist, Writers, an Editor and Fact-checker, and a Designer for covers. The shared studio-designer (documents and one-pagers) can also be hired on request. Each works in its own herdr pane.

## What it makes

For each post that passes the director's review, in the job desk's `out/` folder:

- `<slug>.json` the exact payload the eva-core Blog Autopilot expects (`blog.Payload`, eva-core PR #182)
- `<slug>.png` a 16:9 cover with no text in it
- `<slug>.sources.md` the competitor claims, with URL and date checked
- `summary.md` one page for Mark: what, why, target query, search volume, what needs his eye

Default job: three posts, at least two fan-side (festival resale, "bush doof" and similar), the rest promoter-side. Posts are extras alongside the Autopilot, not a replacement for it. The director edits hard: up to two numbered revision rounds per post, then the piece is cut.

## How to start it

1. Install the roles (once, and after any change): `synthia-squad install growth`. It copies `squads/growth/agents/` to `~/.claude/agents/` and `squad.yaml` to `~/.config/synthia/squads/`.
2. Start a job: `synthia-squad start growth "A week of blog posts, three, two fan-side" --slug week-of-posts`, or tell Synthia "get growth on this week's posts".
3. Watch the panes in the `squads` herdr workspace. When the director runs `synthia-squad done`, Synthia tells you the job is ready.
4. Read `out/summary.md` in the job desk (`~/.local/share/synthia/squads/growth/jobs/<job>/`), then approve or reject from there.

## Guardrails

- Drafts only. Nobody publishes, sends, posts or emails. Mark is the only approver. Nothing is pushed to the blog API or eva-core yet (it has no enqueue tool); payloads wait in `out/`.
- Competitor fees are fetched fresh from the competitor's own page, cited with URL and date, and dated in the post. If it cannot be checked, it comes out. This is the one place the squad is allowed what the Autopilot lint forbids (competitor figures); each such post says so in its `warnings`.
- eventflo's own fee is always the placeholder `[[EVENTFLO FEE — Mark/Corey sign-off]]`.
- Only the verified eventflo feature facts may be claimed. No invented people, quotes, stats or reviews. Nothing touches checkout.
- Australian English. Same lint as the Autopilot (title, excerpt, 900 to 1,600 word body, 3 to 5 FAQs, one `/lets-talk` call to action, no external links).
- At most four specialists live at once. SEO data comes from DataForSEO through the middo247 server; the job is capped at about US$2.
