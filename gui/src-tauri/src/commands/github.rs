//! GitHub Issues Tauri commands.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubLabel {
    name: String,
    color: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubIssue {
    number: u32,
    title: String,
    state: String,
    labels: Vec<GitHubLabel>,
    assignees: Vec<GitHubAssignee>,
    #[serde(rename = "createdAt")]
    created_at: String,
    #[serde(rename = "updatedAt")]
    updated_at: String,
    url: String,
    body: String,
    milestone: Option<GitHubMilestone>,
    comments: Vec<serde_json::Value>,
    repository: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubAssignee {
    login: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubMilestone {
    title: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubConfig {
    repos: Vec<String>,
    refresh_interval_seconds: u64,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubIssuesCache {
    fetched_at: String,
    issues: Vec<GitHubIssue>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct GitHubIssuesResponse {
    issues: Vec<GitHubIssue>,
    fetched_at: String,
    error: Option<String>,
}

fn get_github_config_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia");
    config_dir.join("github.json")
}

fn get_github_cache_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia");
    config_dir.join("github-issues-cache.json")
}

#[tauri::command]
pub fn get_github_config() -> GitHubConfig {
    let path = get_github_config_path();
    if let Ok(content) = fs::read_to_string(&path) {
        if let Ok(config) = serde_json::from_str::<GitHubConfig>(&content) {
            return config;
        }
    }
    GitHubConfig {
        repos: Vec::new(),
        refresh_interval_seconds: 300,
    }
}

#[tauri::command]
pub fn save_github_config(repos: Vec<String>, refresh_interval_seconds: u64) -> AppResult<String> {
    let config = GitHubConfig {
        repos,
        refresh_interval_seconds,
    };
    let path = get_github_config_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| AppError::Io(format!("Failed to create config dir: {}", e)))?;
    }
    let json = serde_json::to_string_pretty(&config)
        .map_err(|e| AppError::Json(format!("Failed to serialize config: {}", e)))?;
    fs::write(&path, json).map_err(|e| AppError::Io(format!("Failed to write config: {}", e)))?;
    Ok("saved".to_string())
}

#[tauri::command]
pub fn get_github_issues(force_refresh: bool) -> GitHubIssuesResponse {
    let config = get_github_config();

    if config.repos.is_empty() {
        return GitHubIssuesResponse {
            issues: Vec::new(),
            fetched_at: String::new(),
            error: None,
        };
    }

    // Return cached data immediately unless force refresh is requested
    let cache_path = get_github_cache_path();
    if !force_refresh {
        if let Ok(content) = fs::read_to_string(&cache_path) {
            if let Ok(cache) = serde_json::from_str::<GitHubIssuesCache>(&content) {
                return GitHubIssuesResponse {
                    issues: cache.issues,
                    fetched_at: cache.fetched_at,
                    error: None,
                };
            }
        }
    }

    // Check if gh is installed
    if Command::new("gh").arg("--version").output().is_err() {
        return GitHubIssuesResponse {
            issues: Vec::new(),
            fetched_at: String::new(),
            error: Some("GitHub CLI (gh) is not installed. Install it from https://cli.github.com/".to_string()),
        };
    }

    // Fetch issues from each repo
    let mut all_issues: Vec<GitHubIssue> = Vec::new();
    let mut errors: Vec<String> = Vec::new();

    for repo in &config.repos {
        match Command::new("gh")
            .args([
                "issue", "list",
                "--assignee", "@me",
                "--repo", repo,
                "--json", "number,title,state,labels,assignees,createdAt,updatedAt,url,body,milestone,comments",
                "--state", "all",
                "--limit", "100",
            ])
            .output()
        {
            Ok(output) => {
                if output.status.success() {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    match serde_json::from_str::<Vec<GitHubIssue>>(&stdout) {
                        Ok(mut issues) => {
                            for issue in &mut issues {
                                issue.repository = Some(repo.clone());
                            }
                            all_issues.extend(issues);
                        }
                        Err(e) => {
                            errors.push(format!("{}: parse error: {}", repo, e));
                        }
                    }
                } else {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    errors.push(format!("{}: {}", repo, stderr.trim()));
                }
            }
            Err(e) => {
                errors.push(format!("{}: {}", repo, e));
            }
        }
    }

    // Sort by updated_at descending
    all_issues.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));

    let fetched_at = chrono::Utc::now().to_rfc3339();

    // Write cache
    let cache = GitHubIssuesCache {
        fetched_at: fetched_at.clone(),
        issues: all_issues.clone(),
    };
    if let Ok(json) = serde_json::to_string_pretty(&cache) {
        let _ = fs::write(&cache_path, json);
    }

    GitHubIssuesResponse {
        issues: all_issues,
        fetched_at,
        error: if errors.is_empty() { None } else { Some(errors.join("; ")) },
    }
}
