//! Sidebar Shortcuts panel data source.
//!
//! Surfaces shell aliases (parsed from `bash -ic 'alias'` output) and a
//! static list of Synthia hotkeys to the Tauri frontend.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tokio::process::Command;
use tokio::time::timeout;

const CACHE_TTL: Duration = Duration::from_secs(60);
const SHELL_TIMEOUT: Duration = Duration::from_secs(5);

static CACHE: Mutex<Option<(Vec<AliasEntry>, Instant)>> = Mutex::new(None);

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
pub struct AliasEntry {
    pub name: String,
    pub expansion: String,
}

/// Parse a single line of `alias` builtin output.
///
/// Accepts both bash's `alias name='expansion'` and zsh's `name='expansion'`
/// styles. Returns None for lines that don't match (blank lines,
/// continuations, garbage).
pub fn parse_alias_line(line: &str) -> Option<AliasEntry> {
    let stripped = line.trim().strip_prefix("alias ").unwrap_or_else(|| line.trim());
    let (name, raw_expansion) = stripped.split_once('=')?;
    let name = name.trim();
    if name.is_empty() || name.contains(char::is_whitespace) {
        return None;
    }
    let expansion = raw_expansion.trim();
    let unquoted = if (expansion.starts_with('\'') && expansion.ends_with('\''))
        || (expansion.starts_with('"') && expansion.ends_with('"'))
    {
        if expansion.len() >= 2 {
            &expansion[1..expansion.len() - 1]
        } else {
            expansion
        }
    } else {
        expansion
    };
    Some(AliasEntry {
        name: name.to_string(),
        expansion: unquoted.to_string(),
    })
}

fn detect_shell() -> String {
    std::env::var("SHELL")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "/bin/bash".into())
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task 10)
pub async fn get_shell_aliases() -> Vec<AliasEntry> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, fetched_at)) = guard.as_ref() {
            if fetched_at.elapsed() < CACHE_TTL {
                return items.clone();
            }
        }
    }

    let shell = detect_shell();
    let result = timeout(
        SHELL_TIMEOUT,
        Command::new(&shell).args(["-ic", "alias"]).output(),
    )
    .await;

    let output = match result {
        Ok(Ok(out)) => out,
        _ => return cached_or_empty(),
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut entries: Vec<AliasEntry> = stdout.lines().filter_map(parse_alias_line).collect();
    entries.sort_by(|a, b| a.name.cmp(&b.name));
    entries.dedup_by(|a, b| a.name == b.name);

    if let Ok(mut guard) = CACHE.lock() {
        *guard = Some((entries.clone(), Instant::now()));
    }
    entries
}

fn cached_or_empty() -> Vec<AliasEntry> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, _)) = guard.as_ref() {
            return items.clone();
        }
    }
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bash_format() {
        assert_eq!(
            parse_alias_line("alias ll='ls -la'"),
            Some(AliasEntry {
                name: "ll".into(),
                expansion: "ls -la".into(),
            })
        );
    }

    #[test]
    fn zsh_format() {
        assert_eq!(
            parse_alias_line("ll='ls -la'"),
            Some(AliasEntry {
                name: "ll".into(),
                expansion: "ls -la".into(),
            })
        );
    }

    #[test]
    fn double_quoted_expansion() {
        assert_eq!(
            parse_alias_line(r#"alias gp="git push""#),
            Some(AliasEntry {
                name: "gp".into(),
                expansion: "git push".into(),
            })
        );
    }

    #[test]
    fn unquoted_expansion() {
        assert_eq!(
            parse_alias_line("alias here=pwd"),
            Some(AliasEntry {
                name: "here".into(),
                expansion: "pwd".into(),
            })
        );
    }

    #[test]
    fn equals_in_expansion() {
        assert_eq!(
            parse_alias_line("alias kubectl='kubectl --context=prod'"),
            Some(AliasEntry {
                name: "kubectl".into(),
                expansion: "kubectl --context=prod".into(),
            })
        );
    }

    #[test]
    fn rejects_blank_and_garbage() {
        assert_eq!(parse_alias_line(""), None);
        assert_eq!(parse_alias_line("   "), None);
        assert_eq!(parse_alias_line("nope no equals here"), None);
        assert_eq!(parse_alias_line("=bare"), None);
        assert_eq!(parse_alias_line("name with space='x'"), None);
    }
}
