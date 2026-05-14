//! YouTube channel feed for the status-bar rotator.
//!
//! Reads channel ids from `~/.config/synthia/config.yaml`'s `youtube.channels`
//! key, fetches each channel's Atom feed in parallel, merges + sorts by
//! published timestamp, and returns the top 12 most recent videos. The
//! request-level cache (30 minutes) keeps the rotator cheap to poll.

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use futures::future::join_all;
use serde::{Deserialize, Serialize};
use serde_yaml::Value;

const CACHE_TTL: Duration = Duration::from_secs(30 * 60);
const MAX_ITEMS: usize = 12;
const PER_REQUEST_TIMEOUT: Duration = Duration::from_secs(8);

static HTTP: OnceLock<reqwest::Client> = OnceLock::new();
static CACHE: Mutex<Option<(Vec<VideoItem>, Instant)>> = Mutex::new(None);

fn http_client() -> &'static reqwest::Client {
    HTTP.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(PER_REQUEST_TIMEOUT)
            .user_agent("synthia-gui/0.1.0 (+https://synthia-ai.com)")
            .build()
            .expect("reqwest client builds")
    })
}

#[derive(Serialize, Clone, Debug)]
pub struct VideoItem {
    pub title: String,
    pub channel_name: String,
    pub video_url: String,
    pub thumbnail_url: Option<String>,
    pub published: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ChannelEntry {
    pub name: String,
    pub id: String,
}

fn synthia_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    PathBuf::from(home).join(".config/synthia/config.yaml")
}

/// Read the YouTube channel list from `~/.config/synthia/config.yaml`.
/// Missing file, missing key, or malformed YAML all yield an empty Vec —
/// the rotator just shows nothing rather than crashing.
pub fn read_channels_from_yaml(path: &std::path::Path) -> Vec<ChannelEntry> {
    let body = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    let root: Value = match serde_yaml::from_str(&body) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };
    let channels = match root.get("youtube").and_then(|y| y.get("channels")) {
        Some(c) => c,
        None => return Vec::new(),
    };
    serde_yaml::from_value::<Vec<ChannelEntry>>(channels.clone()).unwrap_or_default()
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task 17)
pub async fn get_youtube_videos() -> Vec<VideoItem> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, fetched_at)) = guard.as_ref() {
            if fetched_at.elapsed() < CACHE_TTL {
                return items.clone();
            }
        }
    }

    let channels = read_channels_from_yaml(&synthia_config_path());
    if channels.is_empty() {
        return cached_or_empty();
    }

    let client = http_client();
    let fetches = channels
        .iter()
        .map(|ch| fetch_channel(client, ch.clone()));
    let results = join_all(fetches).await;

    let mut all: Vec<VideoItem> = results.into_iter().flatten().collect();
    all.sort_by(|a, b| b.published.cmp(&a.published));
    all.truncate(MAX_ITEMS);

    if let Ok(mut guard) = CACHE.lock() {
        *guard = Some((all.clone(), Instant::now()));
    }
    all
}

async fn fetch_channel(client: &reqwest::Client, ch: ChannelEntry) -> Vec<VideoItem> {
    let url = format!(
        "https://www.youtube.com/feeds/videos.xml?channel_id={}",
        ch.id
    );
    let body = match client.get(&url).send().await {
        Ok(r) => match r.bytes().await {
            Ok(b) => b,
            Err(_) => return Vec::new(),
        },
        Err(_) => return Vec::new(),
    };
    let parsed = match feed_rs::parser::parse(body.as_ref()) {
        Ok(f) => f,
        Err(_) => return Vec::new(),
    };

    parsed
        .entries
        .into_iter()
        .filter_map(|entry| {
            let title = entry.title.map(|t| t.content)?;
            let video_url = entry.links.first().map(|l| l.href.clone())?;
            let published = entry.published.map(|d| d.to_rfc3339());
            let thumbnail_url = entry
                .media
                .iter()
                .flat_map(|m| m.thumbnails.iter())
                .next()
                .map(|t| t.image.uri.clone());
            Some(VideoItem {
                title,
                channel_name: ch.name.clone(),
                video_url,
                thumbnail_url,
                published,
            })
        })
        .collect()
}

fn cached_or_empty() -> Vec<VideoItem> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, _)) = guard.as_ref() {
            return items.clone();
        }
    }
    Vec::new()
}

fn invalidate_cache() {
    if let Ok(mut guard) = CACHE.lock() {
        *guard = None;
    }
}

fn rewrite_channels(channels: &[ChannelEntry]) -> Result<(), String> {
    let path = synthia_config_path();
    let existing = std::fs::read_to_string(&path).unwrap_or_default();
    let pairs: Vec<(String, String)> = channels
        .iter()
        .map(|c| (c.name.clone(), c.id.clone()))
        .collect();
    let updated = crate::yaml_writer::write_youtube_channels(&existing, &pairs);
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    std::fs::write(&path, updated).map_err(|e| e.to_string())?;
    invalidate_cache();
    Ok(())
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task C)
pub async fn list_youtube_channels() -> Vec<ChannelEntry> {
    read_channels_from_yaml(&synthia_config_path())
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task C)
pub async fn add_youtube_channel(
    name: String,
    id: String,
) -> Result<Vec<ChannelEntry>, String> {
    let name = name.trim().to_string();
    let id = id.trim().to_string();
    if name.is_empty() {
        return Err("name cannot be empty".into());
    }
    if !id.starts_with("UC") || id.len() < 20 {
        return Err("id must be a YouTube channel id starting with UC".into());
    }
    let mut current = read_channels_from_yaml(&synthia_config_path());
    if current.iter().any(|c| c.id == id) {
        return Err("channel already in list".into());
    }
    current.push(ChannelEntry { name, id });
    rewrite_channels(&current)?;
    Ok(current)
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task C)
pub async fn remove_youtube_channel(id: String) -> Result<Vec<ChannelEntry>, String> {
    let mut current = read_channels_from_yaml(&synthia_config_path());
    let before = current.len();
    current.retain(|c| c.id != id);
    if current.len() == before {
        return Err("channel id not found".into());
    }
    rewrite_channels(&current)?;
    Ok(current)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn read_channels_missing_file() {
        let p = std::path::Path::new("/tmp/synthia-test-nonexistent.yaml");
        let _ = std::fs::remove_file(p);
        assert!(read_channels_from_yaml(p).is_empty());
    }

    #[test]
    fn read_channels_missing_key() {
        let p = std::env::temp_dir().join("synthia-test-no-yt.yaml");
        let mut f = std::fs::File::create(&p).unwrap();
        writeln!(f, "stt_engine: cloud").unwrap();
        assert!(read_channels_from_yaml(&p).is_empty());
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn read_channels_full_section() {
        let p = std::env::temp_dir().join("synthia-test-yt.yaml");
        let mut f = std::fs::File::create(&p).unwrap();
        writeln!(
            f,
            "youtube:\n  channels:\n    - name: \"Cole\"\n      id: \"UC1\"\n    - name: \"AI King\"\n      id: \"UC2\"\n"
        )
        .unwrap();
        let chans = read_channels_from_yaml(&p);
        assert_eq!(chans.len(), 2);
        assert_eq!(chans[0].name, "Cole");
        assert_eq!(chans[1].id, "UC2");
        let _ = std::fs::remove_file(&p);
    }
}
