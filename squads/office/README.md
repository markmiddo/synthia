# Office squad

An AI team that keeps the eventflo board tidy and drafts the monthly development update. A Chief of Staff (Opus) hires a Project Manager, an Development Release Writer and, for PDFs, the shared Designer (all Sonnet).

## What it does

- **Daily board sweep** (`office-pm`): checks the GitHub boards against the project-management skill. Finds stale issues, wrong or missing Type, status that disagrees with the linked PR, missing labels or assignee, duplicates and issues in the wrong repo. It fixes the safe housekeeping itself (Type, column, labels, board placement) and logs every change. Closing is only ever a proposal. Output: `out/board-report.md` (what changed, what needs Mark, nudges) and `out/nudges.md`.
- **Team nudges**: a short friendly message per teammate falling behind. **Drafts only** for the first week (until Mark says otherwise). Add the line `nudges: send` to a brief to let the PM send them as Slack DMs.
- **Monthly development update** (`office-dev-release`): the month's shipped work in plain language, labelled headline platform numbers if the sales tool is available, tone matched to earlier updates found in Drive. Output: a private Google Doc draft, `out/dev-update.md`, a list of numbers it was unsure of, and a one-page PDF from the designer.

## How to start it

1. Install once, and after any change: `synthia-squad install office` (installs the squad yaml, the office agents and the shared `studio-designer`; nothing is overwritten without `--force`).
2. Start a job:
   - `synthia-squad start office "Daily board sweep" --slug board-sweep`
   - `synthia-squad start office "Monthly development update for September 2026" --slug dev-update`
   - or tell Synthia "get office on the board sweep".
3. Read `out/summary.md` in the job desk (`~/.local/share/synthia/squads/office/jobs/<job>/`).

Timers for the daily sweep (weekdays 07:30) and the monthly update (1st, 08:00) are in `deploy/squads/`; they are not enabled by default.

## Guardrails

- Drafts only. Mark is the only approver. Nothing goes to customers, organisers, investors or the team without him. Hard stops: production promote, money, messages to customers or organisers.
- The PM never closes or deletes an issue, never touches a teammate's PR or branch, never nudges Mark, and verifies a linked PR really fixes the issue (and read the last comments) before moving anything.
- Nudges are drafts unless the brief has `nudges: send`. Setting `fixes: off` in a brief makes the sweep report-only.
- The development update never emails, shares or posts. The Google Doc stays private to Mark's account. Shipped means live in production, not merged to development. Every number is labelled with its source and period; anything uncertain is listed for Mark.
