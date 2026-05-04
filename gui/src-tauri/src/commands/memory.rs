//! Memory Tauri commands.

use std::collections::HashMap;
use std::fs;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::get_memory_dir;

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct MemoryEntry {
    category: String,
    data: serde_json::Value,
    tags: Vec<String>,
    date: Option<String>,
    line_number: usize,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct MemoryStats {
    total: usize,
    categories: HashMap<String, usize>,
    tags: Vec<(String, usize)>,
}

pub(crate) fn get_memory_categories() -> HashMap<&'static str, &'static str> {
    let mut map = HashMap::new();
    map.insert("bug", "bugs.jsonl");
    map.insert("pattern", "patterns.jsonl");
    map.insert("arch", "architecture.jsonl");
    map.insert("gotcha", "gotchas.jsonl");
    map.insert("stack", "stack.jsonl");
    map
}

pub(crate) fn load_memory_entries(category: Option<&str>) -> Vec<MemoryEntry> {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();
    let mut entries = Vec::new();

    let files_to_read: Vec<_> = if let Some(cat) = category {
        if let Some(filename) = categories.get(cat) {
            vec![(cat, *filename)]
        } else {
            return entries;
        }
    } else {
        categories.iter().map(|(k, v)| (*k, *v)).collect()
    };

    for (cat, filename) in files_to_read {
        let filepath = memory_dir.join(filename);
        if !filepath.exists() {
            continue;
        }

        if let Ok(content) = fs::read_to_string(&filepath) {
            for (line_num, line) in content.lines().enumerate() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }

                if let Ok(mut data) = serde_json::from_str::<serde_json::Value>(line) {
                    let tags = data.get("tags")
                        .and_then(|t| t.as_array())
                        .map(|arr| arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect())
                        .unwrap_or_default();

                    let date = data.get("date")
                        .and_then(|d| d.as_str())
                        .map(|s| s.to_string());

                    // Remove tags and date from data for cleaner display
                    if let Some(obj) = data.as_object_mut() {
                        obj.remove("tags");
                        obj.remove("date");
                    }

                    entries.push(MemoryEntry {
                        category: cat.to_string(),
                        data,
                        tags,
                        date,
                        line_number: line_num,
                    });
                }
            }
        }
    }

    entries
}

#[tauri::command]
pub fn get_memory_stats() -> MemoryStats {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();
    let mut cat_counts: HashMap<String, usize> = HashMap::new();
    let mut tag_counts: HashMap<String, usize> = HashMap::new();
    let mut total = 0;

    for (cat, filename) in &categories {
        let filepath = memory_dir.join(filename);
        if !filepath.exists() {
            cat_counts.insert(cat.to_string(), 0);
            continue;
        }

        if let Ok(content) = fs::read_to_string(&filepath) {
            let mut count = 0;
            for line in content.lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }

                if let Ok(data) = serde_json::from_str::<serde_json::Value>(line) {
                    count += 1;

                    // Count tags
                    if let Some(tags) = data.get("tags").and_then(|t| t.as_array()) {
                        for tag in tags {
                            if let Some(tag_str) = tag.as_str() {
                                *tag_counts.entry(tag_str.to_string()).or_insert(0) += 1;
                            }
                        }
                    }
                }
            }
            total += count;
            cat_counts.insert(cat.to_string(), count);
        } else {
            cat_counts.insert(cat.to_string(), 0);
        }
    }

    // Sort tags by count
    let mut tags: Vec<_> = tag_counts.into_iter().collect();
    tags.sort_by(|a, b| b.1.cmp(&a.1));
    tags.truncate(15);

    MemoryStats {
        total,
        categories: cat_counts,
        tags,
    }
}

#[tauri::command]
pub fn get_memory_entries(category: Option<String>) -> Vec<MemoryEntry> {
    load_memory_entries(category.as_deref())
}

#[tauri::command]
pub fn search_memory(query: String) -> Vec<MemoryEntry> {
    let all_entries = load_memory_entries(None);
    let query_lower = query.to_lowercase();
    let query_tags: Vec<_> = query.split(',').map(|s| s.trim().to_lowercase()).collect();

    all_entries.into_iter().filter(|entry| {
        // Check if any tag matches
        let tag_match = entry.tags.iter().any(|t| {
            query_tags.iter().any(|qt| t.to_lowercase().contains(qt))
        });

        if tag_match {
            return true;
        }

        // Check full text in data
        let data_str = entry.data.to_string().to_lowercase();
        data_str.contains(&query_lower)
    }).collect()
}

#[tauri::command]
pub fn update_memory_entry(
    category: String,
    line_number: usize,
    data: serde_json::Value,
    tags: Vec<String>,
) -> AppResult<String> {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();

    let filename = categories
        .get(category.as_str())
        .ok_or_else(|| AppError::Validation(format!("Unknown category: {}", category)))?;

    let filepath = memory_dir.join(filename);

    let content = fs::read_to_string(&filepath)
        .map_err(|e| AppError::Io(format!("Failed to read file: {}", e)))?;

    let mut lines: Vec<String> = content.lines().map(str::to_owned).collect();

    if line_number >= lines.len() {
        return Err(AppError::Validation("Invalid line number".to_string()));
    }

    // Build new entry
    let mut new_data = data;
    if let Some(obj) = new_data.as_object_mut() {
        obj.insert("tags".to_string(), serde_json::json!(tags));
        obj.insert(
            "date".to_string(),
            serde_json::json!(chrono::Local::now().format("%Y-%m").to_string()),
        );
    }

    let new_line = serde_json::to_string(&new_data)
        .map_err(|e| AppError::Json(format!("Failed to serialize: {}", e)))?;

    lines[line_number] = new_line;

    let new_content = lines.join("\n");
    fs::write(&filepath, new_content)
        .map_err(|e| AppError::Io(format!("Failed to write file: {}", e)))?;

    Ok("Entry updated".to_string())
}

#[tauri::command]
pub fn delete_memory_entry(category: String, line_number: usize) -> AppResult<String> {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();

    let filename = categories
        .get(category.as_str())
        .ok_or_else(|| AppError::Validation(format!("Unknown category: {}", category)))?;

    let filepath = memory_dir.join(filename);

    let content = fs::read_to_string(&filepath)
        .map_err(|e| AppError::Io(format!("Failed to read file: {}", e)))?;

    let mut lines: Vec<String> = content.lines().map(str::to_owned).collect();

    if line_number >= lines.len() {
        return Err(AppError::Validation("Invalid line number".to_string()));
    }

    lines.remove(line_number);

    let new_content = lines.join("\n");
    fs::write(&filepath, new_content)
        .map_err(|e| AppError::Io(format!("Failed to write file: {}", e)))?;

    Ok("Entry deleted".to_string())
}

#[cfg(test)]
mod tests {
    #[test]
    fn owned_string_replacement_pattern() {
        let content = "line0\nline1\nline2\n";
        let mut lines: Vec<String> = content.lines().map(str::to_owned).collect();
        lines[1] = "replaced".to_string();
        assert_eq!(lines.join("\n"), "line0\nreplaced\nline2");
    }
}
