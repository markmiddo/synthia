# Product Dashboard Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Product" tab to the Synthia Tauri GUI that embeds the existing eventflo Product Dashboard and keeps it live via Synthia-owned refresh.

**Architecture:** Two Rust IPC commands (`get_product_dashboard_html`, `refresh_product_dashboard`) in a new `commands/product.rs`, plus a React `renderProductSection()` that shows the assembled HTML in an `<iframe srcDoc>`. The HTML command inlines the `data/dashboard.js` sidecar into `dashboard.html` and rewrites its loader so the embedded frame reads inlined data instead of fetching a file. The refresh command shells out to `refresh.sh`. The source tool at `~/.claude/tools/product-dashboard/` is never modified.

**Tech Stack:** Rust + Tauri v2, React + TypeScript, `@tauri-apps/api/core` `invoke`.

## Global Constraints

- Dashboard dir: `~/.claude/tools/product-dashboard` (resolved via `get_claude_dir().join("tools/product-dashboard")`).
- Rust errors use the existing typed `AppError` (variants: `Io`, `Path`, `Validation`, `NotFound`, `Process`, …). No `unwrap()` on I/O.
- Rust clippy gate: zero warnings (`cargo clippy --all-targets -- -D warnings`).
- Do NOT modify the source tool files under `~/.claude/tools/product-dashboard/`.
- Auto-refresh interval: **15 minutes**, hard-coded constant, only while the Product section is active.
- Brand: "Product Dashboard" title; keep capital-S "Synthia".

---

### Task 1: Rust command — assemble embedded dashboard HTML

**Files:**
- Create: `gui/src-tauri/src/commands/product.rs`
- Modify: `gui/src-tauri/src/commands/mod.rs` (add `pub mod product;`)
- Modify: `gui/src-tauri/src/lib.rs` (add `get_product_dashboard_dir()` helper + register command in `generate_handler!`)

**Interfaces:**
- Consumes: `crate::error::AppError`, `crate::get_claude_dir` (existing, in `lib.rs`).
- Produces:
  - `pub(crate) fn get_product_dashboard_dir() -> PathBuf` (in `lib.rs`)
  - `pub fn build_embedded_html(html: &str, sidecar_js: &str) -> String` (in `product.rs`)
  - `#[tauri::command] pub async fn get_product_dashboard_html() -> Result<String, AppError>`

- [ ] **Step 1: Write the failing test**

Create `gui/src-tauri/src/commands/product.rs` with only the test + a stub:

```rust
//! Product Dashboard Tauri commands.
//!
//! Embeds the existing eventflo Product Dashboard (`~/.claude/tools/product-dashboard/`)
//! into the GUI. `dashboard.html` normally loads its data from a relative
//! `data/dashboard.js` sidecar (falling back to `fetch`) — neither works inside an
//! embedded iframe, so we inline the sidecar and rewrite the loader to read the
//! inlined global. The source tool is never modified.

use crate::error::AppError;
use crate::get_product_dashboard_dir;

/// Inline the data sidecar into the page and rewrite the loader so an embedded
/// frame reads `window.DASHBOARD_DATA` directly instead of loading a file.
pub fn build_embedded_html(html: &str, sidecar_js: &str) -> String {
    // Neutralize any literal </script> inside JSON string values so the inline
    // script tag can't be closed early.
    let safe = sidecar_js.replace("</script>", "<\\/script>");
    let injected = format!("<head>\n  <script>{safe}</script>");
    html.replacen("<head>", &injected, 1).replace(
        "return loadSidecar().then(data =>",
        "return Promise.resolve(window.DASHBOARD_DATA).then(data =>",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embeds_data_and_rewrites_loader() {
        let html = "<html><head>\n</head><body><script>\n    function loadSidecar(){}\n    function loadData(){ return loadSidecar().then(data => data); }\n</script></body></html>";
        let sidecar = "window.DASHBOARD_DATA = {\"x\":1};\n";

        let out = build_embedded_html(html, sidecar);

        assert!(out.contains("window.DASHBOARD_DATA = {\"x\":1};"), "sidecar inlined");
        assert!(out.contains("Promise.resolve(window.DASHBOARD_DATA).then(data =>"), "loader rewritten");
        assert!(!out.contains("return loadSidecar().then(data =>"), "old loader call gone");
    }

    #[test]
    fn escapes_nested_script_close() {
        let html = "<head>\n</head>";
        let sidecar = "window.DASHBOARD_DATA = {\"t\":\"a</script>b\"};";
        let out = build_embedded_html(html, sidecar);
        assert!(!out.contains("a</script>b"), "nested close escaped");
        assert!(out.contains("a<\\/script>b"), "escaped form present");
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gui/src-tauri && cargo test --lib product`
Expected: compile error — `get_product_dashboard_dir` and `AppError` import unused / `get_product_dashboard_dir` not found (helper added next step). If it compiles and passes the two `build_embedded_html` tests already, that is acceptable (the transform is pure); proceed.

- [ ] **Step 3: Add the dir helper and the command**

In `gui/src-tauri/src/lib.rs`, next to `get_claude_dir()` / `get_memory_dir()`:

```rust
pub(crate) fn get_product_dashboard_dir() -> PathBuf {
    get_claude_dir().join("tools/product-dashboard")
}
```

Append to `gui/src-tauri/src/commands/product.rs` (after `build_embedded_html`, before `#[cfg(test)]`):

```rust
/// Return the fully self-contained dashboard HTML with data inlined.
#[tauri::command]
pub async fn get_product_dashboard_html() -> Result<String, AppError> {
    let dir = get_product_dashboard_dir();
    let html_path = dir.join("dashboard.html");
    if !html_path.exists() {
        return Err(AppError::NotFound(
            "Product dashboard not found — run the morning tool once to generate it.".into(),
        ));
    }
    let html = std::fs::read_to_string(&html_path).map_err(|e| AppError::Io(e.to_string()))?;
    // Sidecar may not exist yet (never refreshed); the page has its own no-data
    // handling and the first background refresh will generate it.
    let sidecar = std::fs::read_to_string(dir.join("data/dashboard.js")).unwrap_or_default();
    Ok(build_embedded_html(&html, &sidecar))
}
```

In `gui/src-tauri/src/commands/mod.rs`, add (alphabetical order, after `pub mod overlay;`):

```rust
pub mod product;
```

In `gui/src-tauri/src/lib.rs` `generate_handler!` list, add near the other command entries:

```rust
            commands::product::get_product_dashboard_html,
```

- [ ] **Step 4: Run tests + clippy to verify pass**

Run: `cd gui/src-tauri && cargo test --lib product && cargo clippy --all-targets -- -D warnings`
Expected: both `product::tests` pass; zero clippy warnings.

- [ ] **Step 5: Commit**

```bash
git add gui/src-tauri/src/commands/product.rs gui/src-tauri/src/commands/mod.rs gui/src-tauri/src/lib.rs
git commit -m "feat(product): get_product_dashboard_html command with inlined data"
```

---

### Task 2: Rust command — refresh the dashboard data

**Files:**
- Modify: `gui/src-tauri/src/commands/product.rs` (add `refresh_product_dashboard`)
- Modify: `gui/src-tauri/src/lib.rs` (register command)

**Interfaces:**
- Consumes: `get_product_dashboard_dir`, `AppError`, `tauri::async_runtime::spawn_blocking`.
- Produces: `#[tauri::command] pub async fn refresh_product_dashboard() -> Result<String, AppError>` (returns `"refreshed"` on success).

- [ ] **Step 1: Add the command**

Append to `gui/src-tauri/src/commands/product.rs` (before `#[cfg(test)]`):

```rust
/// Regenerate the dashboard data by running the tool's `refresh.sh`.
/// Runs off the UI thread; `refresh.sh` keeps prior data on partial failure.
#[tauri::command]
pub async fn refresh_product_dashboard() -> Result<String, AppError> {
    let dir = get_product_dashboard_dir();
    if !dir.join("refresh.sh").exists() {
        return Err(AppError::NotFound("refresh.sh not found".into()));
    }
    let output = tauri::async_runtime::spawn_blocking(move || {
        std::process::Command::new("bash")
            .arg("refresh.sh")
            .current_dir(&dir)
            .output()
    })
    .await
    .map_err(|e| AppError::Process(e.to_string()))?
    .map_err(|e| AppError::Process(e.to_string()))?;

    if !output.status.success() {
        return Err(AppError::Process(format!(
            "refresh.sh failed: {}",
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    Ok("refreshed".to_string())
}
```

- [ ] **Step 2: Register the command**

In `gui/src-tauri/src/lib.rs` `generate_handler!`, add below the previous entry:

```rust
            commands::product::refresh_product_dashboard,
```

- [ ] **Step 3: Build + clippy to verify it compiles clean**

Run: `cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings`
Expected: builds; zero warnings. (No unit test — this shells out to `gh`; verified manually in Task 4.)

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/commands/product.rs gui/src-tauri/src/lib.rs
git commit -m "feat(product): refresh_product_dashboard command runs refresh.sh"
```

---

### Task 3: Frontend — Product tab

**Files:**
- Modify: `gui/src/App.tsx` (Section union, state, nav button, `renderProductSection`, load/refresh functions, effect, main-content wiring)
- Modify: `gui/src/App.css` (product panel styles)

**Interfaces:**
- Consumes: Rust commands `get_product_dashboard_html` (`-> string`), `refresh_product_dashboard` (`-> string`).
- Produces: `renderProductSection()` used in the `<main className="main-content">` switch.

- [ ] **Step 1: Add `"product"` to the Section union**

`gui/src/App.tsx:398` — change:

```tsx
type Section = "worktrees" | "knowledge" | "agents" | "security" | "voice" | "memory" | "config" | "github";
```
to:
```tsx
type Section = "worktrees" | "knowledge" | "agents" | "security" | "voice" | "memory" | "config" | "github" | "product";
```

- [ ] **Step 2: Add state (near the GitHub state block around line 516-525)**

```tsx
  // Product dashboard state
  const [productHtml, setProductHtml] = useState<string>("");
  const [productError, setProductError] = useState<string | null>(null);
  const [productRefreshing, setProductRefreshing] = useState(false);
  const [productRefreshedAt, setProductRefreshedAt] = useState<string>("");
```

- [ ] **Step 3: Add load + refresh functions and the section renderer**

Add alongside the other `renderXSection` functions (e.g. after `renderGithubSection`):

```tsx
  async function loadProductHtml() {
    try {
      const html = await invoke<string>("get_product_dashboard_html");
      setProductHtml(html);
      setProductError(null);
    } catch (e) {
      setProductError(typeof e === "string" ? e : JSON.stringify(e));
    }
  }

  async function refreshProductDashboard() {
    setProductRefreshing(true);
    try {
      await invoke("refresh_product_dashboard");
      await loadProductHtml();
      setProductRefreshedAt(new Date().toLocaleTimeString("en-AU"));
    } catch (e) {
      setProductError(typeof e === "string" ? e : JSON.stringify(e));
    } finally {
      setProductRefreshing(false);
    }
  }

  function renderProductSection() {
    return (
      <div className="product-section">
        <div className="product-toolbar">
          <span className="product-title">Product Dashboard</span>
          <span className="product-status">
            {productRefreshing
              ? "Refreshing…"
              : productRefreshedAt
              ? `Updated ${productRefreshedAt}`
              : ""}
          </span>
          <button
            className="task-panel-btn primary"
            onClick={refreshProductDashboard}
            disabled={productRefreshing}
          >
            Refresh
          </button>
        </div>
        {productError ? (
          <div className="product-empty">{productError}</div>
        ) : (
          <iframe
            className="product-frame"
            title="Product Dashboard"
            srcDoc={productHtml}
          />
        )}
      </div>
    );
  }
```

- [ ] **Step 4: Add the load-on-open + interval effect**

Add a new `useEffect` alongside the other section effects (near line 649-669):

```tsx
  useEffect(() => {
    if (currentSection !== "product") return;
    loadProductHtml();
    refreshProductDashboard();
    const id = setInterval(refreshProductDashboard, 15 * 60 * 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSection]);
```

- [ ] **Step 5: Add the nav button**

In the `<nav>` block, after the GitHub nav-item (around line 2291-2297), add:

```tsx
          <button
            className={`nav-item ${currentSection === "product" ? "active" : ""}`}
            onClick={() => setCurrentSection("product")}
          >
            <span className="nav-item-icon">&#128202;</span>
            Product
          </button>
```

- [ ] **Step 6: Wire into main-content switch**

At `gui/src/App.tsx` ~line 4425, add inside `<main className="main-content">`:

```tsx
          {currentSection === "product" && renderProductSection()}
```

- [ ] **Step 7: Add CSS**

Append to `gui/src/App.css`:

```css
.product-section {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.product-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.product-title { font-weight: 600; }
.product-status { color: #9a9aa8; font-size: 12px; margin-left: auto; }
.product-frame {
  flex: 1;
  width: 100%;
  border: none;
  background: #08080c;
}
.product-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9a9aa8;
  padding: 40px;
  text-align: center;
}
```

- [ ] **Step 8: Typecheck + build the frontend**

Run: `cd gui && npm run build`
Expected: TypeScript compiles, Vite build succeeds, no unused-var errors.

- [ ] **Step 9: Commit**

```bash
git add gui/src/App.tsx gui/src/App.css
git commit -m "feat(product): Product dashboard tab with embedded iframe + auto-refresh"
```

---

### Task 4: Build the app + manual verification

**Files:** none (verification only)

- [ ] **Step 1: Full release build**

Run: `cd gui/src-tauri && cargo build --release`
Expected: builds clean.

- [ ] **Step 2: Launch the dev GUI**

Kill any running instance first (an old process blocks the new one), then run the app (`cd gui && npm run tauri dev`, or the project's usual launch). Confirm no console errors on startup.

- [ ] **Step 3: Verify the tab**

- Click the **Product** nav item → the dashboard panels render inside the iframe (bugs / car park / tasks / release / PRs / deploys panels visible).
- The toolbar shows "Refreshing…" then "Updated <time>" after the initial background refresh completes.
- Click **Refresh** → status returns to "Refreshing…" then updates; panel data reloads.
- Switch to another tab and back → no duplicate intervals / errors in the console.
- Temporarily rename `~/.claude/tools/product-dashboard/dashboard.html` and reopen the tab → friendly "not found" message shows instead of a crash. Restore the file.

- [ ] **Step 4: Final commit (if any tweaks were needed)**

```bash
git add -A
git commit -m "fix(product): verification tweaks"
```

---

## Self-Review

**Spec coverage:**
- Embed existing HTML → Task 1 (`build_embedded_html` + `get_product_dashboard_html`). ✓
- New Product sidebar tab → Task 3 (Section union, nav button, main-content switch). ✓
- Synthia owns refresh (on-open + manual + 15-min interval) → Task 2 (command) + Task 3 (functions + effect). ✓
- Inline data + loader rewrite (no CORS/file://) → Task 1 transform + escaping test. ✓
- Path resolution + friendly missing-dir empty state → Task 1 (`get_product_dashboard_dir`, `NotFound`) + Task 3 (`product-empty`). ✓
- Refresh never blanks page on partial failure → relies on `refresh.sh` behavior; command surfaces non-zero exit as error while prior snapshot stays displayed (Task 2 + Task 3 keep `productHtml`). ✓
- Rust unit test for transform → Task 1 Steps 1-4. ✓
- Source tool untouched → no task modifies `~/.claude/tools/...`. ✓

**Placeholder scan:** No TBD/TODO; all steps carry concrete code + exact commands.

**Type consistency:** `get_product_dashboard_dir` (lib.rs) used identically in Tasks 1 & 2. `build_embedded_html(html, sidecar_js)` signature matches its test and caller. Frontend `get_product_dashboard_html` returns `string`; `refresh_product_dashboard` return value unused. State names (`productHtml`, `productError`, `productRefreshing`, `productRefreshedAt`) consistent across Steps 2-4.
