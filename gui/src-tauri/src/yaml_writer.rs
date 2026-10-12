//! Comment-preserving YAML writer for the word replacements in config.yaml.
//!
//! This intentionally does NOT use `serde_yaml::to_string` for whole-file
//! serialization, because that would erase user-authored comments and reorder
//! unrelated sections. It walks the existing file line-by-line and surgically
//! replaces only the `word_replacements:` section.

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

#[cfg(test)]
mod tests {
    use super::*;

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
}
