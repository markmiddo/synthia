//! Comment-preserving YAML writers.
//!
//! These functions intentionally do NOT use `serde_yaml::to_string` for
//! whole-file serialization, because that would erase user-authored comments
//! and reorder unrelated sections. Instead they walk the existing file
//! line-by-line and surgically replace only the targeted section.
//!
//! Reads of these same files use `serde_yaml::from_str` via `crate::config`
//! structs — round-tripping through serde would be more idiomatic but would
//! lose every `#`-prefixed line and every blank-line separator the user
//! placed in `~/.config/synthia/config.yaml` and `worktrees.yaml`. This
//! split-responsibility design (typed reads, surgical writes) is the
//! pragmatic compromise.

use std::collections::HashSet;

/// Replace specific top-level scalar keys in a flat YAML config with new
/// values. Other keys, comments, blank lines, and section ordering are
/// preserved. Keys not present in `existing` are NOT appended (caller's job
/// to decide whether to add them).
pub fn write_synthia_config_keys(existing: &str, updates: &[(&str, String)]) -> String {
    let mut out_lines: Vec<String> = Vec::with_capacity(existing.lines().count());

    for line in existing.lines() {
        let trimmed = line.trim_start();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            out_lines.push(line.to_string());
            continue;
        }

        if let Some((key_part, _)) = trimmed.split_once(':') {
            let key = key_part.trim();
            // Only rewrite top-level keys (no leading whitespace). Indented
            // keys belong to a nested mapping (e.g. `word_replacements:`)
            // and are handled by `write_word_replacements`.
            let is_top_level = line.starts_with(|c: char| !c.is_whitespace());
            if is_top_level {
                if let Some((_, new_val)) = updates.iter().find(|(k, _)| *k == key) {
                    out_lines.push(format!("{key}: {new_val}"));
                    continue;
                }
            }
        }

        out_lines.push(line.to_string());
    }

    let mut joined = out_lines.join("\n");
    if existing.ends_with('\n') && !joined.ends_with('\n') {
        joined.push('\n');
    }
    joined
}

/// Replace the `word_replacements:` section in a config file with the given
/// from→to mappings. Comments and other top-level sections are preserved.
/// If the section does not exist it is appended at end-of-file with a
/// header comment.
pub fn write_word_replacements(existing: &str, replacements: &[(String, String)]) -> String {
    let mut out = String::new();
    let mut in_section = false;
    let mut wrote_section = false;
    let ends_newline = existing.ends_with('\n');

    for line in existing.lines() {
        let trimmed = line.trim_start();

        if !in_section && trimmed.starts_with("word_replacements:") {
            // Emit the header + new entries in place
            out.push_str("word_replacements:\n");
            for (from, to) in replacements {
                out.push_str(&format!("  {from}: {to}\n"));
            }
            in_section = true;
            wrote_section = true;
            continue;
        }

        if in_section {
            // Skip the old indented entries
            let is_indented = line.starts_with(' ') || line.starts_with('\t');
            if is_indented && !trimmed.is_empty() && !trimmed.starts_with('#') {
                continue;
            }
            // Hit a blank line or comment — section is done; emit the line.
            // (Trailing comments inside the old section will follow the
            //  new entries; that's acceptable.)
            if !is_indented && !trimmed.is_empty() {
                in_section = false;
            }
        }

        out.push_str(line);
        out.push('\n');
    }

    if !wrote_section {
        // Append the section
        if !out.is_empty() && !out.ends_with("\n\n") {
            if !out.ends_with('\n') {
                out.push('\n');
            }
            out.push('\n');
        }
        out.push_str("# Word replacements for dictation\n");
        out.push_str("word_replacements:\n");
        for (from, to) in replacements {
            out.push_str(&format!("  {from}: {to}\n"));
        }
    }

    if !ends_newline {
        // Caller's original had no trailing newline; trim one off
        if out.ends_with('\n') {
            out.pop();
        }
    }
    out
}

/// Append a single host to the `hosts:` list of an egress allowlist YAML.
///
/// Behaviour:
///   - Empty input → emit a fresh skeleton with header + `hosts:` + the host.
///   - Existing file with `hosts:` → append `  - <host>` at the end of the
///     section, preserving comments and ordering.
///   - Host already present in `hosts:` → return the input unchanged.
///   - File without a `hosts:` section but with other content → append a
///     `hosts:` section at end.
///
/// We never reformat the file: every existing line is emitted verbatim
/// except for the single-line insertion. This keeps the user's comments,
/// blank lines, and the `ips:` section (if any) untouched.
pub fn append_allowlist_host(existing: &str, host: &str) -> String {
    if existing.trim().is_empty() {
        // Fresh skeleton.
        return format!(
            "# Synthia egress allowlist\n# Hosts here are resolved to IPs every hour and treated as allowed.\nhosts:\n  - {host}\n"
        );
    }

    let lines: Vec<&str> = existing.lines().collect();
    let ends_newline = existing.ends_with('\n');

    // Locate the `hosts:` header line (top-level) and the index where the
    // section ends (first line at column 0 that isn't an indented entry, a
    // blank line, or a comment).
    let mut hosts_header: Option<usize> = None;
    for (i, line) in lines.iter().enumerate() {
        let trimmed = line.trim_start();
        let is_top_level = !line.starts_with(|c: char| c.is_whitespace());
        if is_top_level && trimmed.starts_with("hosts:") {
            hosts_header = Some(i);
            break;
        }
    }

    let header_idx = match hosts_header {
        Some(i) => i,
        None => {
            // No `hosts:` section — append one at end.
            let mut out = String::from(existing);
            if !out.ends_with('\n') {
                out.push('\n');
            }
            // Add a separator blank line if the file doesn't already end in one.
            if !out.ends_with("\n\n") {
                out.push('\n');
            }
            out.push_str("hosts:\n");
            out.push_str(&format!("  - {host}\n"));
            if !ends_newline {
                // Caller's original had no trailing newline — match that.
                if out.ends_with('\n') {
                    out.pop();
                }
            }
            return out;
        }
    };

    // Walk forward from header_idx + 1 collecting list-item lines (`  - foo`)
    // and tracking the last index that belongs to the section. Comments and
    // blank lines inside the section are preserved verbatim.
    let mut last_in_section = header_idx;
    let mut existing_hosts: HashSet<String> = HashSet::new();
    for (i, line) in lines.iter().enumerate().skip(header_idx + 1) {
        let trimmed = line.trim_start();
        let is_top_level = !line.starts_with(|c: char| c.is_whitespace())
            && !trimmed.is_empty()
            && !trimmed.starts_with('#');
        if is_top_level {
            // Section ended at the previous line.
            break;
        }
        last_in_section = i;
        // Parse `  - <host>` entries to detect duplicates.
        if let Some(rest) = trimmed.strip_prefix("- ") {
            let entry = rest.trim().trim_matches(|c: char| c == '"' || c == '\'');
            if !entry.is_empty() {
                existing_hosts.insert(entry.to_string());
            }
        } else if let Some(rest) = trimmed.strip_prefix('-') {
            // Tolerate `-foo` (no space) just in case.
            let entry = rest.trim().trim_matches(|c: char| c == '"' || c == '\'');
            if !entry.is_empty() {
                existing_hosts.insert(entry.to_string());
            }
        }
    }

    if existing_hosts.contains(host) {
        // Already present — no-op.
        return existing.to_string();
    }

    // Find the last list-item line in the section (skipping trailing blanks
    // and comments) so the new entry goes adjacent to existing items, not
    // after a sea of trailing whitespace.
    let mut insert_after = header_idx;
    for (i, line) in lines
        .iter()
        .enumerate()
        .take(last_in_section + 1)
        .skip(header_idx + 1)
    {
        if line.trim_start().starts_with('-') {
            insert_after = i;
        }
    }

    let mut out_lines: Vec<String> = Vec::with_capacity(lines.len() + 1);
    for (i, line) in lines.iter().enumerate() {
        out_lines.push((*line).to_string());
        if i == insert_after {
            out_lines.push(format!("  - {host}"));
        }
    }
    let mut joined = out_lines.join("\n");
    if ends_newline {
        joined.push('\n');
    }
    joined
}

/// Rewrite the `worktrees.yaml` file with the given repo list. Header
/// comments are re-emitted from a fixed template (the file is small and
/// fully managed by the GUI, so a template is acceptable here).
pub fn write_worktrees_repos(repos: &[String]) -> String {
    let mut out = String::from("# Repositories to scan for worktrees\n");
    out.push_str("# Add paths to git repos you want to track\n");
    out.push_str("repos:\n");
    for repo in repos {
        out.push_str(&format!("  - {repo}\n"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_synthia_config_keys_preserves_comments() {
        let input = "# Top comment\nuse_local_stt: false\n# Mid comment\ntts_speed: 1.0\n";
        let updates = vec![("tts_speed", "1.5".to_string())];
        let out = write_synthia_config_keys(input, &updates);
        assert!(out.contains("# Top comment"));
        assert!(out.contains("# Mid comment"));
        assert!(out.contains("tts_speed: 1.5"));
        assert!(!out.contains("tts_speed: 1.0"));
    }

    #[test]
    fn write_synthia_config_keys_preserves_unchanged_keys() {
        let input = "use_local_stt: true\ntts_voice: alloy\ntts_speed: 1.0\n";
        let updates = vec![("tts_speed", "2.0".to_string())];
        let out = write_synthia_config_keys(input, &updates);
        assert!(out.contains("use_local_stt: true"));
        assert!(out.contains("tts_voice: alloy"));
        assert!(out.contains("tts_speed: 2.0"));
    }

    #[test]
    fn write_synthia_config_keys_preserves_blank_lines() {
        let input = "use_local_stt: true\n\ntts_speed: 1.0\n";
        let out = write_synthia_config_keys(input, &[("tts_speed", "1.5".to_string())]);
        // Blank line between sections survives
        assert!(out.contains("use_local_stt: true\n\n"));
    }

    #[test]
    fn write_word_replacements_replaces_section_in_place() {
        let input = "use_local_stt: true\nword_replacements:\n  old: new\n  foo: bar\n# trailing comment\n";
        let pairs = vec![("hello".to_string(), "hi".to_string())];
        let out = write_word_replacements(input, &pairs);
        assert!(out.contains("use_local_stt: true"));
        assert!(out.contains("hello: hi"));
        assert!(!out.contains("old: new"));
        assert!(!out.contains("foo: bar"));
        assert!(out.contains("# trailing comment"));
    }

    #[test]
    fn write_word_replacements_appends_section_if_missing() {
        let input = "use_local_stt: true\n";
        let pairs = vec![("hello".to_string(), "hi".to_string())];
        let out = write_word_replacements(input, &pairs);
        assert!(out.contains("use_local_stt: true"));
        assert!(out.contains("word_replacements:"));
        assert!(out.contains("hello: hi"));
    }

    #[test]
    fn write_worktrees_repos_emits_header_and_list() {
        let out = write_worktrees_repos(&["/a/b".to_string(), "/c/d".to_string()]);
        assert!(out.contains("repos:"));
        assert!(out.contains("- /a/b"));
        assert!(out.contains("- /c/d"));
        assert!(out.starts_with("# Repositories to scan for worktrees"));
    }

    #[test]
    fn write_worktrees_repos_handles_empty_list() {
        let out = write_worktrees_repos(&[]);
        assert!(out.contains("repos:"));
        assert!(!out.contains("-"));
    }

    #[test]
    fn append_allowlist_host_creates_section_if_missing() {
        // Empty input → fresh skeleton.
        let out = append_allowlist_host("", "example.com");
        assert!(out.contains("hosts:"));
        assert!(out.contains("- example.com"));
        assert!(out.starts_with("# Synthia egress allowlist"));

        // File with other content but no `hosts:` → append section at end.
        let input = "# my notes\nips:\n  - 10.0.0.1\n";
        let out = append_allowlist_host(input, "foo.bar");
        assert!(out.contains("ips:"));
        assert!(out.contains("- 10.0.0.1"));
        assert!(out.contains("hosts:"));
        assert!(out.contains("- foo.bar"));
        // Original lines stay verbatim.
        assert!(out.contains("# my notes"));
    }

    #[test]
    fn append_allowlist_host_preserves_comments() {
        let input = "# top comment\nhosts:\n  # inner comment\n  - first.com\n  - second.com\n# trailing\nips:\n  - 10.0.0.1\n";
        let out = append_allowlist_host(input, "third.com");
        assert!(out.contains("# top comment"));
        assert!(out.contains("# inner comment"));
        assert!(out.contains("# trailing"));
        assert!(out.contains("- first.com"));
        assert!(out.contains("- second.com"));
        assert!(out.contains("- third.com"));
        assert!(out.contains("ips:"));
        assert!(out.contains("- 10.0.0.1"));
        // The new entry should appear after `second.com` (the last list item),
        // before the `# trailing` comment / `ips:` section.
        let third_pos = out.find("- third.com").unwrap();
        let trailing_pos = out.find("# trailing").unwrap();
        let ips_pos = out.find("ips:").unwrap();
        assert!(third_pos < trailing_pos);
        assert!(third_pos < ips_pos);
    }

    #[test]
    fn append_allowlist_host_skips_duplicates() {
        let input = "hosts:\n  - already.here\n  - also.here\n";
        let out = append_allowlist_host(input, "already.here");
        // No-op: returns input verbatim.
        assert_eq!(out, input);
        // Sanity: count of `- already.here` is exactly one.
        assert_eq!(out.matches("- already.here").count(), 1);
    }
}
