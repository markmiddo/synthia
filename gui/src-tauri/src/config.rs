//! Strongly-typed YAML config structs.
//!
//! These types mirror the on-disk shape of `~/.config/synthia/config.yaml`
//! and `~/.config/synthia/worktrees.yaml`. They are used for **reads** only —
//! see `yaml_writer.rs` (CP6) for the comment-preserving save paths.
//!
//! Reuses field names from the original `SynthiaConfig`/`WorktreesRepoConfig`
//! structs in `lib.rs` so the React-facing JSON shape stays identical.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SynthiaConfigYaml {
    #[serde(default)]
    pub use_local_stt: bool,
    #[serde(default)]
    pub use_local_llm: bool,
    #[serde(default)]
    pub use_local_tts: bool,
    #[serde(default)]
    pub local_stt_model: String,
    #[serde(default)]
    pub local_llm_model: String,
    #[serde(default)]
    pub local_tts_voice: String,
    #[serde(default)]
    pub assistant_model: String,
    #[serde(default)]
    pub tts_voice: String,
    #[serde(default = "default_tts_speed")]
    pub tts_speed: f64,
    #[serde(default = "default_conversation_memory")]
    pub conversation_memory: i32,
    #[serde(default)]
    pub show_notifications: bool,
    #[serde(default)]
    pub play_sound_on_record: bool,
    /// Inline `word_replacements: { from: to }` map — preserved as-is.
    #[serde(default)]
    pub word_replacements: HashMap<String, String>,
}

fn default_tts_speed() -> f64 {
    1.0
}

fn default_conversation_memory() -> i32 {
    10
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct WorktreesYaml {
    #[serde(default)]
    pub repos: Vec<String>,
}

/// User-managed egress allowlist, read from
/// `~/.config/synthia/security/allowlist.yaml`. `hosts` are resolved to IPs
/// at allowlist-load time (1h TTL); `ips` are matched literally as
/// `IpAddr::parse`-compatible strings.
///
/// The egress module reads this file via its own private struct (kept private
/// because cache/lifecycle concerns belong inside `egress.rs`). This public
/// type exists for any future direct consumer (e.g. an allowlist editor UI)
/// and round-trip-tests the on-disk shape.
#[allow(dead_code)] // public API for future allowlist-editor command
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct UserAllowlist {
    #[serde(default)]
    pub hosts: Vec<String>,
    #[serde(default)]
    pub ips: Vec<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn synthia_config_parses_minimal() {
        let yaml = "use_local_stt: true\ntts_speed: 1.5\n";
        let cfg: SynthiaConfigYaml = serde_yaml::from_str(yaml).unwrap();
        assert!(cfg.use_local_stt);
        assert_eq!(cfg.tts_speed, 1.5);
        assert_eq!(cfg.conversation_memory, 10); // default
    }

    #[test]
    fn synthia_config_parses_word_replacements() {
        let yaml = "word_replacements:\n  hello: hi\n  world: planet\n";
        let cfg: SynthiaConfigYaml = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(cfg.word_replacements.get("hello"), Some(&"hi".to_string()));
        assert_eq!(cfg.word_replacements.len(), 2);
    }

    #[test]
    fn synthia_config_handles_empty_file() {
        let cfg: SynthiaConfigYaml = serde_yaml::from_str("{}").unwrap();
        assert_eq!(cfg.tts_speed, 1.0);
        assert!(cfg.word_replacements.is_empty());
    }

    #[test]
    fn synthia_config_ignores_unknown_keys() {
        let yaml = "use_local_stt: true\nfuture_setting: 42\n";
        let cfg: SynthiaConfigYaml = serde_yaml::from_str(yaml).unwrap();
        assert!(cfg.use_local_stt);
    }

    #[test]
    fn worktrees_parses_repo_list() {
        let yaml = "repos:\n  - /home/u/repo1\n  - /home/u/repo2\n";
        let cfg: WorktreesYaml = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(cfg.repos.len(), 2);
        assert_eq!(cfg.repos[0], "/home/u/repo1");
    }

    #[test]
    fn worktrees_handles_empty() {
        let cfg: WorktreesYaml = serde_yaml::from_str("{}").unwrap();
        assert!(cfg.repos.is_empty());
    }

    #[test]
    fn user_allowlist_round_trip() {
        let original = UserAllowlist {
            hosts: vec!["api.example.com".to_string(), "internal.local".to_string()],
            ips: vec!["10.0.0.42".to_string(), "192.0.2.5".to_string()],
        };
        let yaml = serde_yaml::to_string(&original).unwrap();
        let parsed: UserAllowlist = serde_yaml::from_str(&yaml).unwrap();
        assert_eq!(parsed.hosts, original.hosts);
        assert_eq!(parsed.ips, original.ips);

        // Empty file default-fills both fields.
        let empty: UserAllowlist = serde_yaml::from_str("{}").unwrap();
        assert!(empty.hosts.is_empty());
        assert!(empty.ips.is_empty());

        // Either field can be absent.
        let hosts_only: UserAllowlist =
            serde_yaml::from_str("hosts:\n  - foo.com\n").unwrap();
        assert_eq!(hosts_only.hosts, vec!["foo.com".to_string()]);
        assert!(hosts_only.ips.is_empty());
    }
}
