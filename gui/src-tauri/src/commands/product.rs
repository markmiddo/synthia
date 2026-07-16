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
