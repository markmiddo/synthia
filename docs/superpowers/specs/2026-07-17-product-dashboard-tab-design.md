# Product Dashboard Tab — Design

**Date:** 2026-07-17
**Status:** Approved for planning

## Problem

The eventflo Product Dashboard (`~/.claude/tools/product-dashboard/dashboard.html`) is a self-contained
local page that renders eight panels from live GitHub Projects data (#2 Bugs, #10 Car Park, #11 Tasks,
#15 v3.1 Release), open PRs per repo, deploys, and personal Google Tasks. A heavy `refresh.sh` regenerates
`data/dashboard.json` + `data/dashboard.js` (many `gh` CLI calls + Google Tasks + a Go deploys helper);
cron pre-refreshes it. Today it is opened as a static `file://` page during the morning routine — only as
fresh as the last refresh, and living outside Synthia.

Goal: bring the dashboard into the Synthia Tauri GUI as a first-class tab that renders the existing page and
keeps its data live via Synthia-owned refresh.

## Decisions (locked)

- **Render:** embed the existing `dashboard.html` — no React port of the panels. One source of truth with the
  morning tool; zero re-design.
- **Placement:** new dedicated `"product"` section in the sidebar (not nested under GitHub).
- **Refresh owner:** Synthia runs `refresh.sh` (on open, manual button, and a modest interval). The existing
  cron can coexist harmlessly.

## Architecture

Two Rust IPC commands + one React panel rendering a single `<iframe>`.

### Data / rendering pipeline

The loader in `dashboard.html` always tries to load the `data/dashboard.js` sidecar via a relative
`<script src>` and falls back to `fetch('data/dashboard.json')`. Both fail inside an embedded frame
(no base path, no `file://` origin). So the data must be **inlined** into the HTML before it is embedded.

**Rust command `get_product_dashboard_html() -> Result<String, AppError>`**

1. Resolve the dashboard dir (see Path resolution).
2. Read `dashboard.html`.
3. Read `data/dashboard.js` — it is already `window.DASHBOARD_DATA = {…};`.
4. Inject the sidecar contents as an inline `<script>…</script>` immediately before the page's main
   `<script>` block, so `window.DASHBOARD_DATA` is set before any page code runs.
5. Rewrite the loader call `loadSidecar()` → `Promise.resolve(window.DASHBOARD_DATA)` so `loadData()` reads
   the inlined global instead of attempting a file load. (String replace of a single unique substring:
   `return loadSidecar().then(data =>` → `return Promise.resolve(window.DASHBOARD_DATA).then(data =>`.)
6. Return the assembled self-contained HTML string.

No CORS, no `file://`, no Tauri asset-protocol scope changes required. The **source tool is not modified.**

**Frontend:** the Product panel renders `<iframe srcDoc={html} className="product-frame" />` filling the
panel. External Google-Fonts `@import` degrades to system fonts when offline (cosmetic only); project CSP is
already `null` so fonts load when online.

### Refresh

**Rust command `refresh_product_dashboard() -> Result<RefreshResult, AppError>`**

- Runs `bash refresh.sh` with the dashboard dir as CWD, off the UI thread (async task /
  `tokio::task::spawn_blocking` consistent with existing command patterns). Returns success/failure plus a
  completion timestamp.
- `refresh.sh` already keeps the previous data file when a `gh` fetch fails (rate limit etc.), so a partial
  or failed refresh never blanks the dashboard.

**Frontend flow (Product panel):**

1. On section open → call `get_product_dashboard_html` immediately and show the last snapshot (fast).
2. Kick a background `refresh_product_dashboard`; while running, show a subtle "refreshing" indicator.
3. On completion → re-call `get_product_dashboard_html` and swap the iframe `srcDoc`.
4. Manual **Refresh** button repeats steps 2–3.
5. Interval auto-refresh: default **15 minutes**, ticking only while the Product section is active
   (cleared on unmount / section change). Hard-coded constant.

### Path resolution

Add a helper resolving `~/.claude/tools/product-dashboard`, home-dir based, mirroring the existing
`paths.rs` conventions (canonicalize-checked). If the directory or `dashboard.html` is missing, the command
returns a typed `AppError` and the panel shows a friendly "dashboard not found — run the morning tool once"
message rather than crashing.

### Wiring

- Add `"product"` to the `Section` union in `App.tsx`; add a sidebar nav button (icon + label "Product").
- Add a `ProductPanel` render branch.
- Register both commands in the Tauri invoke handler (`lib.rs` + `commands/mod.rs`), in a new
  `commands/product.rs` module.

## Error handling

- Missing dir / `dashboard.html` → typed `AppError`, friendly empty-state in the panel.
- `refresh.sh` non-zero exit → surface a non-blocking error toast/line; keep displaying the prior snapshot.
- `data/dashboard.js` missing (never refreshed) → `get_product_dashboard_html` still returns the page HTML;
  the page's own no-data handling applies, and the initial background refresh generates the sidecar.

## Testing

- Rust unit test for the HTML assembly transform: given fixture `dashboard.html` + `dashboard.js`, assert the
  inlined `<script>` is present and the `loadSidecar()` call was rewritten (Rust `cargo test --lib`).
- Rust: path-resolution helper returns expected path; missing-dir yields `AppError`.
- Manual: open Product tab, confirm panels render, manual Refresh updates the snapshot, interval fires while
  active and stops when switching away.

## Out of scope (YAGNI)

- No React reimplementation of the eight panels.
- No settings UI for the refresh interval (constant, trivially editable).
- No removal/rewrite of the existing cron.
- No changes to the eventflo source tool.
