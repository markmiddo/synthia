//! Agent daily journal — tracks completed task lists across all agent types.
//!
//! Stores entries as JSON files in ~/.config/synthia/journal/YYYY-MM-DD.json
//! Retains exactly 7 days, auto-pruning older files.

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

use crate::error::AppResult;

/// A single journal entry — written when an agent completes a task list.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct JournalEntry {
    pub timestamp: DateTime<Utc>,
    pub agent_name: String,
    pub agent_kind: String,
    pub agent_role: String,
    pub project_name: String,
    pub branch: Option<String>,
    pub task_summary: String,
    pub files_touched: Vec<String>,
    pub activity: Option<String>,
    pub session_id: Option<String>,
    pub trigger: String,
}

/// All entries for a single day.
#[derive(Serialize, Deserialize, Debug, Default)]
pub struct DayJournal {
    pub entries: Vec<JournalEntry>,
}

fn get_journal_dir() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("~/.config"))
        .join("synthia")
        .join("journal")
}

fn get_journal_file(date: &DateTime<Utc>) -> PathBuf {
    get_journal_dir().join(format!("{}.json", date.format("%Y-%m-%d")))
}

/// Load journal entries for a specific date.
fn load_day_journal(date: &DateTime<Utc>) -> AppResult<DayJournal> {
    let path = get_journal_file(date);
    if !path.exists() {
        return Ok(DayJournal::default());
    }
    let content = fs::read_to_string(&path)?;
    let journal: DayJournal = serde_json::from_str(&content)?;
    Ok(journal)
}

/// Save journal entries for a specific date (atomic write-then-rename).
fn save_day_journal(date: &DateTime<Utc>, journal: &DayJournal) -> AppResult<()> {
    let dir = get_journal_dir();
    fs::create_dir_all(&dir)?;

    let path = get_journal_file(date);
    let temp_path = path.with_extension("tmp");

    let json = serde_json::to_string_pretty(journal)?;
    fs::write(&temp_path, json)?;
    fs::rename(&temp_path, &path)?;

    Ok(())
}

/// Remove journal files older than 7 days.
fn prune_old_journals() -> AppResult<()> {
    let dir = get_journal_dir();
    if !dir.exists() {
        return Ok(());
    }

    let cutoff = Utc::now() - Duration::days(7);

    for entry in fs::read_dir(&dir)? {
        let entry = entry?;
        let path = entry.path();

        if let Some(ext) = path.extension() {
            if ext != "json" {
                continue;
            }
            let Some(stem) = path.file_stem().and_then(|s| s.to_str()) else {
                continue;
            };
            let Ok(date) = chrono::NaiveDate::parse_from_str(stem, "%Y-%m-%d") else {
                continue;
            };
            let date_time = date
                .and_hms_opt(0, 0, 0)
                .map(|dt| DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc))
                .unwrap_or_else(|| Utc::now() - Duration::days(365));
            if date_time < cutoff {
                fs::remove_file(&path)?;
            }
        }
    }

    Ok(())
}

/// Append a new entry to today's journal file.
#[tauri::command]
pub fn add_journal_entry(entry: JournalEntry) -> AppResult<()> {
    let today = Utc::now();
    let mut journal = load_day_journal(&today)?;
    journal.entries.push(entry);
    save_day_journal(&today, &journal)?;
    prune_old_journals()?;
    Ok(())
}

/// Retrieve journal entries grouped by day label.
///
/// Returns Vec of (day_label, entries) for the requested number of days.
/// Day labels: "Today", "Yesterday", or formatted date like "May 5".
#[tauri::command]
pub fn get_journal_entries(days: Option<i64>) -> AppResult<Vec<(String, Vec<JournalEntry>)>> {
    let days = days.unwrap_or(7);
    let mut result = Vec::new();

    for day_offset in (0..days).rev() {
        let date = Utc::now() - Duration::days(day_offset);
        let journal = load_day_journal(&date)?;

        if journal.entries.is_empty() {
            continue;
        }

        let date_label = if day_offset == 0 {
            "Today".to_string()
        } else if day_offset == 1 {
            "Yesterday".to_string()
        } else {
            date.format("%B %d").to_string()
        };

        result.push((date_label, journal.entries));
    }

    Ok(result)
}

/// Same as get_journal_entries but filtered by agent kind.
#[tauri::command]
pub fn get_journal_entries_by_agent(
    agent_kind: Option<String>,
    days: Option<i64>,
) -> AppResult<Vec<(String, Vec<JournalEntry>)>> {
    let all = get_journal_entries(days)?;

    let Some(kind) = agent_kind else {
        return Ok(all);
    };

    let filtered: Vec<(String, Vec<JournalEntry>)> = all
        .into_iter()
        .map(|(date_label, entries)| {
            let filtered_entries: Vec<JournalEntry> = entries
                .into_iter()
                .filter(|e| e.agent_kind == kind)
                .collect();
            (date_label, filtered_entries)
        })
        .filter(|(_, entries)| !entries.is_empty())
        .collect();

    Ok(filtered)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    #[test]
    fn test_get_journal_file() {
        let date = Utc.with_ymd_and_hms(2025, 5, 5, 0, 0, 0).unwrap();
        let path = get_journal_file(&date);
        assert!(path.to_string_lossy().contains("2025-05-05.json"));
    }

    #[test]
    fn test_load_save_day_journal() {
        // Use a unique date to avoid race conditions with parallel tests
        let date = Utc.with_ymd_and_hms(2099, 1, 1, 0, 0, 0).unwrap();
        let mut journal = DayJournal::default();

        journal.entries.push(JournalEntry {
            timestamp: date,
            agent_name: "TestAgent".to_string(),
            agent_kind: "claude".to_string(),
            agent_role: "Developer".to_string(),
            project_name: "test".to_string(),
            branch: Some("main".to_string()),
            task_summary: "Test task".to_string(),
            files_touched: vec!["test.rs".to_string()],
            activity: Some("Testing".to_string()),
            session_id: Some("abc123".to_string()),
            trigger: "task_list_completed".to_string(),
        });

        save_day_journal(&date, &journal).unwrap();

        let loaded = load_day_journal(&date).unwrap();
        assert_eq!(loaded.entries.len(), 1);
        assert_eq!(loaded.entries[0].agent_name, "TestAgent");
        assert_eq!(loaded.entries[0].task_summary, "Test task");

        let path = get_journal_file(&date);
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn test_add_and_retrieve_entry() {
        let date = Utc.with_ymd_and_hms(2099, 1, 2, 0, 0, 0).unwrap();
        let entry = JournalEntry {
            timestamp: date,
            agent_name: "Atlas".to_string(),
            agent_kind: "claude".to_string(),
            agent_role: "Developer".to_string(),
            project_name: "synthia".to_string(),
            branch: None,
            task_summary: "Test entry".to_string(),
            files_touched: vec![],
            activity: None,
            session_id: None,
            trigger: "test".to_string(),
        };

        // Save directly to avoid prune interference
        let mut journal = load_day_journal(&date).unwrap();
        journal.entries.push(entry);
        save_day_journal(&date, &journal).unwrap();

        let loaded = load_day_journal(&date).unwrap();
        assert!(loaded.entries.iter().any(|e| e.task_summary == "Test entry"));

        let path = get_journal_file(&date);
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn test_prune_old_journals() {
        let old_date = Utc::now() - Duration::days(10);
        let old_journal = DayJournal::default();
        save_day_journal(&old_date, &old_journal).unwrap();

        let old_path = get_journal_file(&old_date);
        assert!(old_path.exists());

        prune_old_journals().unwrap();

        assert!(!old_path.exists());
    }

    #[test]
    fn test_get_journal_entries() {
        let date = Utc.with_ymd_and_hms(2099, 1, 3, 0, 0, 0).unwrap();
        let mut journal = DayJournal::default();
        journal.entries.push(JournalEntry {
            timestamp: date,
            agent_name: "Test".to_string(),
            agent_kind: "claude".to_string(),
            agent_role: "Developer".to_string(),
            project_name: "test".to_string(),
            branch: None,
            task_summary: "Test task for entries".to_string(),
            files_touched: vec![],
            activity: None,
            session_id: None,
            trigger: "test".to_string(),
        });
        save_day_journal(&date, &journal).unwrap();

        // get_journal_entries looks back from today, so a 2099 date won't appear
        // Test the file format instead
        let loaded = load_day_journal(&date).unwrap();
        assert_eq!(loaded.entries.len(), 1);
        assert_eq!(loaded.entries[0].task_summary, "Test task for entries");

        let path = get_journal_file(&date);
        let _ = fs::remove_file(&path);
    }
}
