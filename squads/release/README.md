# Release squad

An AI team that does the paperwork after a release. A Release Lead (Opus) hires a Help Centre Writer, a Video Editor and, for a one-pager, the shared Designer (all Sonnet).

## What it does

- **Help Centre** (`release-faq`): finds what shipped between the previous and new production tags, checks every organiser Help Centre article that might now be wrong, missing or outdated against the shipped code, and writes new or updated articles as drafts. Output: `out/help-centre-changes.md` (each article marked new / updated / now wrong, with links and publish gates) plus one markdown file per article.
- **Release video** (`release-video`): takes Mark's raw walkthrough recordings, transcribes them, cuts dead air, false starts and repeated takes, adds chapter titles, captions and the eventflo intro and outro from the Remotion template, and renders at low priority and low concurrency. Output: `out/<name>.mp4`, `out/<name>-chapters.md` (YouTube timestamps) and `out/<name>-edl.md` (every cut and why).
- **One-pager** (`studio-designer`, optional): a branded what's-new PDF built from the verified Help Centre changes.

## How to start it

1. Install once, and after any change: `synthia-squad install release` (installs the squad yaml, the release agents and the shared `studio-designer`; nothing is overwritten without `--force`).
2. Start a job. The brief names the release, and optionally a footage folder (an absolute path to the raw recordings), a video name and whether a one-pager is wanted:
   `synthia-squad start release "v3.2 shipped. Footage in /home/markmiddo/Videos/v3.2-raw, video name eventflo-v3-2-release. Also a what's-new one-pager." --slug v3-2`
   or tell Synthia "get release on v3.2".
3. Read `out/summary.md` in the job desk (`~/.local/share/synthia/squads/release/jobs/<job>/`).

The release squad has no timer: it runs on demand.

## Guardrails

- Drafts only. Mark is the only approver. Nothing is published, uploaded or sent. Hard stops: production promote, money, messages to customers or organisers.
- The Help Centre is live production data (eva-ai has no dev environment), so the squad never writes to it. Drafts are markdown files; Mark approves, then they are applied with the admin login.
- Nothing is written as live unless it is on the production branch. Anything gated (flag, opt-in, not yet promoted) is marked as a publish gate.
- The raw footage folder is read only. The video is never uploaded. Rendering runs under `nice` with low concurrency because Mark works on the same machine.
