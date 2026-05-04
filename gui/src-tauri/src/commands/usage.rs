//! Usage stats Tauri command.

use std::fs;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::get_claude_dir;
use crate::state::{AppState, UsageResponseCache, UsageTokenCache};

static HTTP: OnceLock<reqwest::Client> = OnceLock::new();

fn http_client() -> &'static reqwest::Client {
    HTTP.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(15))
            .build()
            .expect("reqwest client builds")
    })
}

#[derive(Serialize, Debug, Clone, Default)]
pub struct UsageStats {
    pub five_hour_pct: f64,
    pub five_hour_resets_at: String,
    pub five_hour_resets_in: String,
    pub seven_day_pct: f64,
    pub seven_day_resets_at: String,
    pub seven_day_resets_in: String,
    pub seven_day_opus_pct: Option<f64>,
    pub seven_day_opus_resets_at: Option<String>,
    pub seven_day_opus_resets_in: Option<String>,
    pub seven_day_sonnet_pct: Option<f64>,
    pub seven_day_sonnet_resets_at: Option<String>,
    pub seven_day_sonnet_resets_in: Option<String>,
    pub subscription_type: Option<String>,
    pub error: Option<String>,
}

#[derive(Deserialize, Debug)]
struct CredsFile {
    #[serde(rename = "claudeAiOauth")]
    claude_ai_oauth: Option<CredsOAuth>,
}

#[derive(Deserialize, Debug)]
struct CredsOAuth {
    #[serde(rename = "accessToken")]
    access_token: Option<String>,
    #[serde(rename = "subscriptionType")]
    subscription_type: Option<String>,
}

#[derive(Deserialize, Debug)]
struct UsageResponse {
    five_hour: Option<UsageWindow>,
    seven_day: Option<UsageWindow>,
    seven_day_opus: Option<UsageWindow>,
    seven_day_sonnet: Option<UsageWindow>,
}

#[derive(Deserialize, Debug)]
struct UsageWindow {
    utilization: Option<f64>,
    resets_at: Option<String>,
}

const TOKEN_TTL: Duration = Duration::from_secs(900);
const RESPONSE_TTL: Duration = Duration::from_secs(60);
const STALE_OK: Duration = Duration::from_secs(600);

fn read_oauth_token_cached(state: &AppState) -> Option<(String, Option<String>)> {
    {
        let cache = state.usage_cache.lock().ok()?;
        if let Some(entry) = cache.as_ref() {
            if entry.fetched_at.elapsed() < TOKEN_TTL {
                return Some((entry.token.clone(), None));
            }
        }
    }
    let creds_path = get_claude_dir().join(".credentials.json");
    let content = fs::read_to_string(&creds_path).ok()?;
    let creds: CredsFile = serde_json::from_str(&content).ok()?;
    let oauth = creds.claude_ai_oauth?;
    let token = oauth.access_token?;
    if let Ok(mut cache) = state.usage_cache.lock() {
        *cache = Some(UsageTokenCache {
            token: token.clone(),
            fetched_at: Instant::now(),
        });
    }
    Some((token, oauth.subscription_type))
}

fn humanize_duration_until(iso: &str) -> String {
    let target = match chrono::DateTime::parse_from_rfc3339(iso) {
        Ok(t) => t,
        Err(_) => return String::new(),
    };
    let now = chrono::Utc::now();
    let delta = target.with_timezone(&chrono::Utc) - now;
    let secs = delta.num_seconds();
    if secs <= 0 {
        return "now".to_string();
    }
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    if h > 0 {
        format!("{}h {}m", h, m)
    } else {
        format!("{}m", m)
    }
}

fn cached_or_error(state: &AppState, err: String) -> UsageStats {
    if let Ok(cache) = state.usage_response_cache.lock() {
        if let Some(entry) = cache.as_ref() {
            if entry.fetched_at.elapsed() < STALE_OK {
                let mut s = entry.stats.clone();
                s.error = Some(format!("{} (showing cached)", err));
                return s;
            }
        }
    }
    UsageStats { error: Some(err), ..Default::default() }
}

#[tauri::command]
pub async fn get_usage_stats(state: tauri::State<'_, AppState>) -> Result<UsageStats, ()> {
    // Fast path: read+drop cache before any await.
    let cached_fresh = {
        let cache = state.usage_response_cache.lock().ok();
        cache.and_then(|c| {
            c.as_ref().and_then(|entry| {
                if entry.fetched_at.elapsed() < RESPONSE_TTL {
                    Some(entry.stats.clone())
                } else {
                    None
                }
            })
        })
    };
    if let Some(stats) = cached_fresh {
        return Ok(stats);
    }

    let (token, subscription_type) = match read_oauth_token_cached(&state) {
        Some(v) => v,
        None => {
            return Ok(UsageStats {
                error: Some("No Claude credentials found".to_string()),
                ..Default::default()
            });
        }
    };

    let resp = http_client()
        .get("https://api.anthropic.com/oauth/usage")
        .header("authorization", format!("Bearer {}", token))
        .header("anthropic-beta", "oauth-2025-04-20")
        .header("accept", "application/json")
        .header("user-agent", "synthia-gui/0.1")
        .send()
        .await;

    let body: UsageResponse = match resp {
        Ok(r) if r.status().is_success() => match r.json::<UsageResponse>().await {
            Ok(b) => b,
            Err(e) => return Ok(cached_or_error(&state, format!("parse error: {}", e))),
        },
        Ok(r) => return Ok(cached_or_error(&state, format!("HTTP {}", r.status()))),
        Err(e) => return Ok(cached_or_error(&state, format!("network: {}", e))),
    };

    let mut stats = UsageStats {
        subscription_type,
        ..Default::default()
    };

    if let Some(w) = body.five_hour {
        stats.five_hour_pct = w.utilization.unwrap_or(0.0);
        if let Some(r) = w.resets_at {
            stats.five_hour_resets_in = humanize_duration_until(&r);
            stats.five_hour_resets_at = r;
        }
    }
    if let Some(w) = body.seven_day {
        stats.seven_day_pct = w.utilization.unwrap_or(0.0);
        if let Some(r) = w.resets_at {
            stats.seven_day_resets_in = humanize_duration_until(&r);
            stats.seven_day_resets_at = r;
        }
    }
    if let Some(w) = body.seven_day_opus {
        stats.seven_day_opus_pct = w.utilization;
        if let Some(r) = w.resets_at {
            stats.seven_day_opus_resets_in = Some(humanize_duration_until(&r));
            stats.seven_day_opus_resets_at = Some(r);
        }
    }
    if let Some(w) = body.seven_day_sonnet {
        stats.seven_day_sonnet_pct = w.utilization;
        if let Some(r) = w.resets_at {
            stats.seven_day_sonnet_resets_in = Some(humanize_duration_until(&r));
            stats.seven_day_sonnet_resets_at = Some(r);
        }
    }

    if let Ok(mut cache) = state.usage_response_cache.lock() {
        *cache = Some(UsageResponseCache {
            stats: stats.clone(),
            fetched_at: Instant::now(),
        });
    }
    Ok(stats)
}
