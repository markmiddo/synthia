# Synthia Squads: High-Level Plan

**Date:** 2026-10-13
**Status:** High-level, agreed in principle with Mark. Detailed spec next session.
**Builds on:** Synthia Jarvis phase 1 (markmiddo/synthia#28) and the eventflo Growth Engine plan
(https://claude.ai/artifact/PMntSVCMGacDCHXLP5Ndpc).

## Idea

Mark designs AI teams in Synthia as an org chart: a director role that hires specialist roles
(Marketing Director, then Copywriter, Designer, SEO Specialist and so on). Each member runs as a
real herdr pane, so they work in parallel and are visible. Mark talks to Synthia ("get marketing
on this week's posts"), Synthia briefs the director, the director runs the team and reviews its
work, and Mark only sees finished drafts to approve.

## Opinion (agreed)

- The value is in sharp roles that know eventflo (voice, real data, Mark's rules), parallel work on
  clear tasks, and one place to steer. The chart is the easy part.
- Keep it shallow: director plus specialists, two levels at most.
- Directors on Opus, specialists on Sonnet, four agents per squad to start.
- The director is a tough editor, not a pass-through.
- Nothing reaches customers on its own: drafts only, and Mark approves.

## What already exists (research, 2026-10-13)

- **Blog engine is built but dev only.**
  - organizer-backend #3324 provides `blog_posts` and an API that takes the Eva service key.
  - fan-experience #1570 provides `/blog`, `/blog/:slug` and the blog sitemap.
  - Production is #3102, riding the v3.2 promote plus the manual Lambda@Edge deploy.
- **Blog Autopilot is built, unmerged and off.** It is eva-core PR #182, head `1b976e7`, with `autopilot.enabled: false`.
  - Writer: Sonnet drafts a post Mon/Wed/Fri at 05:00.
  - Queue and approval: drafts go to the `content_items` queue, a digest goes to Slack #blogs at 08:00, and Mark approves through a signed review link.
  - Publishing: a publisher posts approved drafts to the blog API.
  - Topics: hard-coded in `topics.go`.
  - Facts: no competitor fees allowed, and the eventflo fee is a placeholder until it is signed off.
  - Enable steps are in #3108.
- **No blog writer is running on middo247 today.** None of the 16 eva-core jobs is blog or SEO.
- **Head of Growth plan** (`eventflo/docs/plans/2026-09-29-head-of-growth.md`): design only. It covers:
  - analyst, SEO strategist, writer, adversarial editor/fact-checker, programmatic pages, outreach, distribution, AI visibility and CRO roles,
  - an approver agent that learns from Mark's decisions,
  - DataForSEO, whose credentials are live on middo247.
- **#1475 Marketing Autopilot (eva-ai):** roles for Reddit, syndication, AEO tracker and reputation, none built.
- **Skills available:** the `seo-*` suite (DataForSEO, content-brief, cluster, geo, drift, schema), `nano-banana-pro`, `activecampaign` and `customer-success`. There are no marketing agents yet.
- **SEO review 2026-10-02:** the 8 launch phrases have no measurable search volume. Organizer demand is about 4k a month, and fan-side terms (festival resale, "bush doof" at about 9.9k) are the bigger prize.

## Shape: squads feed the Autopilot, they don't replace it

- **eva-core Autopilot (middo247)** stays the pipeline: queue, digest, approval, publish. It is
  safe, server-side and separate from checkout.
- **Synthia squads (desktop, herdr)** are the thinking layer that fills the queue with better
  drafts. They write into Autopilot's `content_items` through its API.
- **Mark approves** in the digest or by voice ("Synthia, approve today's post"). He is the only approver.

## Phases

0. **Prerequisites.**
   - Merge synthia#28 and murmur#6.
   - Synthia "Act": brain tools to open, brief and watch herdr panes, with parent and child metadata.
   - Merge eva-core#182 and switch the Autopilot on for dev (#3108).
1. **Squad engine in Synthia.**
   - Roles are Claude Code agent files (`~/.claude/agents/growth-*.md`) carrying a persona, skills, tools, model and who they may hire.
   - A squad file holds the org chart and caps.
   - A shared squad desk is a folder per job: brief, work in progress, status.
   - A spawn API lets a director hire through Synthia, never more than the cap.
   - HUD: a "Company" view to design the chart, and live squad clusters in the constellation.
2. **Growth squad v1, the blog.**
   - **Director:** picks the week's mix and edits.
   - **SEO strategist:** writes DataForSEO-driven briefs, replacing the hard-coded topics. Fan-side wins come first.
   - **Writer:** drafts the post.
   - **Editor/fact-checker:** re-fetches competitor pages and cites them with a date (Mark's 2 Oct rule), which unlocks fee-comparison posts.
   - **Designer:** turns `coverImageBrief` into a real cover with nano-banana-pro.
   - **Output:** a finished draft, cover included, in the Autopilot queue.
3. **Distribution and monitoring.**
   - **Distribution:** ActiveCampaign newsletter drafts and social copy drafts, handed off to Corey's CMO team.
   - **Technical SEO and AEO monitor:** seo-drift after deploys, seo-geo citation checks, `llms.txt` and entity work (#1518).
   - **Scoreboard:** in the HUD.
4. **Expand.**
   - Comparison pages and city or genre hubs, kept under the value rule.
   - Cold-email personalisation (Smartlead, never AWS).
   - Further squads.

## Guardrails (from the Growth Engine "four ways we zero")

- Every indexed page carries real data, a real guide or a true comparison. Thin pages are no-indexed.
- Cold email never touches eventflo's AWS.
- Post as eventflo only: no fake accounts and no self-written reviews.
- Nothing touches checkout. Anything on the ticketing platform goes through the release train.
- Drafts only. Mark approves everything. Caps on agents and usage per squad.

## Blockers to production (not to building)

- Mark and Corey sign off the fee wording, and the production blog API key is created (#3108 steps 11–13).
- v3.2 promote plus the Lambda@Edge redeploy (#3102).

## Open decisions for the detailed spec

1. The first job for squad v1: a week of blog posts on dev, or one launch campaign?
2. Whether squad drafts replace the Autopilot writer or run alongside it.
3. Where finished non-blog work lands: Drive handoff to Corey's team, ActiveCampaign drafts, or both.
