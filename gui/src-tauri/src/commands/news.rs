//! AI news feed Tauri command.
//!
//! Pulls https://the-decoder.com/feed/ (RSS), parses with feed-rs, returns
//! top N headlines for the status-bar rotator. 15-minute in-memory cache so
//! we don't hammer the feed every poll cycle.

use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::Serialize;

const FEED_URL: &str = "https://the-decoder.com/feed/";
const CACHE_TTL: Duration = Duration::from_secs(15 * 60);
const MAX_ITEMS: usize = 12;

static HTTP: OnceLock<reqwest::Client> = OnceLock::new();
static CACHE: Mutex<Option<(Vec<NewsItem>, Instant)>> = Mutex::new(None);

fn http_client() -> &'static reqwest::Client {
    HTTP.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .user_agent("synthia-gui/0.1.0 (+https://synthia-ai.com)")
            .build()
            .expect("reqwest client builds")
    })
}

#[derive(Serialize, Debug, Clone)]
pub struct NewsItem {
    pub title: String,
    pub link: String,
    pub published: Option<String>,
    pub source: String,
}

#[tauri::command]
pub async fn get_ai_news() -> Vec<NewsItem> {
    // Fast path: serve cached if fresh.
    {
        if let Ok(guard) = CACHE.lock() {
            if let Some((items, fetched_at)) = guard.as_ref() {
                if fetched_at.elapsed() < CACHE_TTL {
                    return items.clone();
                }
            }
        }
    }

    let body = match http_client().get(FEED_URL).send().await {
        Ok(r) => match r.bytes().await {
            Ok(b) => b,
            Err(_) => return cached_or_empty(),
        },
        Err(_) => return cached_or_empty(),
    };

    let parsed = match feed_rs::parser::parse(body.as_ref()) {
        Ok(f) => f,
        Err(_) => return cached_or_empty(),
    };

    let items: Vec<NewsItem> = parsed
        .entries
        .into_iter()
        .take(MAX_ITEMS)
        .filter_map(|entry| {
            let title = entry.title.map(|t| t.content)?;
            let link = entry.links.first().map(|l| l.href.clone())?;
            let published = entry.published.map(|d| d.to_rfc3339());
            Some(NewsItem {
                title,
                link,
                published,
                source: "The Decoder".to_string(),
            })
        })
        .collect();

    if let Ok(mut guard) = CACHE.lock() {
        *guard = Some((items.clone(), Instant::now()));
    }

    items
}

fn cached_or_empty() -> Vec<NewsItem> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, _)) = guard.as_ref() {
            return items.clone();
        }
    }
    Vec::new()
}
