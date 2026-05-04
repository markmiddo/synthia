//! Weather Tauri command.
//!
//! Hits wttr.in `?format=j1` (no API key, IP-based location) and returns a
//! compact summary suitable for a status-bar chip. Errors fall through to a
//! `WeatherSnapshot { error: Some(...) }` rather than a hard `Err` — the
//! status bar should never disappear because the weather backend hiccupped.

use std::sync::OnceLock;
use std::time::Duration;

use serde::{Deserialize, Serialize};

static HTTP: OnceLock<reqwest::Client> = OnceLock::new();

fn http_client() -> &'static reqwest::Client {
    HTTP.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(8))
            .user_agent("synthia-gui/0.1.0")
            .build()
            .expect("reqwest client builds")
    })
}

#[derive(Serialize, Debug, Clone, Default)]
pub struct WeatherSnapshot {
    pub temp_c: Option<i32>,
    pub conditions: Option<String>,
    pub location: Option<String>,
    pub icon: Option<String>,
    pub error: Option<String>,
}

#[derive(Deserialize, Debug)]
struct WttrResponse {
    nearest_area: Option<Vec<WttrArea>>,
    current_condition: Option<Vec<WttrCondition>>,
}

#[derive(Deserialize, Debug)]
struct WttrArea {
    #[serde(rename = "areaName")]
    area_name: Option<Vec<WttrValue>>,
}

#[derive(Deserialize, Debug)]
struct WttrCondition {
    #[serde(rename = "temp_C")]
    temp_c: Option<String>,
    #[serde(rename = "weatherDesc")]
    weather_desc: Option<Vec<WttrValue>>,
    #[serde(rename = "weatherCode")]
    weather_code: Option<String>,
}

#[derive(Deserialize, Debug)]
struct WttrValue {
    value: String,
}

fn weather_emoji(code: &str) -> &'static str {
    // wttr.in weatherCode → emoji mapping. Codes from open-meteo / WMO.
    match code {
        "113" => "☀️",
        "116" => "⛅",
        "119" | "122" => "☁️",
        "143" | "248" | "260" => "🌫️",
        "176" | "263" | "266" | "281" | "284" | "293" | "296" => "🌦️",
        "299" | "302" | "305" | "308" | "311" | "314" => "🌧️",
        "200" | "386" | "389" | "392" | "395" => "⛈️",
        "179" | "227" | "230" | "317" | "320" | "323" | "326" | "329"
        | "332" | "335" | "338" | "350" | "362" | "365" | "368" | "371"
        | "374" | "377" => "❄️",
        _ => "🌡️",
    }
}

#[tauri::command]
pub async fn get_weather() -> WeatherSnapshot {
    let resp = match http_client()
        .get("https://wttr.in/?format=j1")
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            return WeatherSnapshot {
                error: Some(format!("network: {e}")),
                ..Default::default()
            };
        }
    };
    if !resp.status().is_success() {
        return WeatherSnapshot {
            error: Some(format!("HTTP {}", resp.status())),
            ..Default::default()
        };
    }
    let body: WttrResponse = match resp.json().await {
        Ok(b) => b,
        Err(e) => {
            return WeatherSnapshot {
                error: Some(format!("parse: {e}")),
                ..Default::default()
            };
        }
    };

    let location = body
        .nearest_area
        .as_ref()
        .and_then(|a| a.first())
        .and_then(|a| a.area_name.as_ref())
        .and_then(|n| n.first())
        .map(|v| v.value.clone());

    let current = body
        .current_condition
        .as_ref()
        .and_then(|c| c.first());

    let temp_c = current
        .and_then(|c| c.temp_c.as_ref())
        .and_then(|s| s.parse::<i32>().ok());

    let conditions = current
        .and_then(|c| c.weather_desc.as_ref())
        .and_then(|d| d.first())
        .map(|v| v.value.clone());

    let icon = current
        .and_then(|c| c.weather_code.as_ref())
        .map(|code| weather_emoji(code).to_string());

    WeatherSnapshot {
        temp_c,
        conditions,
        location,
        icon,
        error: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn emoji_maps_known_codes() {
        assert_eq!(weather_emoji("113"), "☀️");
        assert_eq!(weather_emoji("119"), "☁️");
        assert_eq!(weather_emoji("389"), "⛈️");
    }

    #[test]
    fn emoji_falls_back_for_unknown_code() {
        assert_eq!(weather_emoji("999999"), "🌡️");
        assert_eq!(weather_emoji(""), "🌡️");
    }
}
