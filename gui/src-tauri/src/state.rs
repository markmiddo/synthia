//! Tauri-managed application state, replacing static `Mutex<Option<T>>` globals.

use std::collections::HashMap;
use std::process::Child;
use std::time::Instant;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use portable_pty::{Child as PtyChild, MasterPty};
use serde::Serialize;
use tokio::task::JoinHandle;
use uuid::Uuid;

use crate::commands::native_term::NativeTermRegistry;
use crate::commands::usage::UsageStats;

#[derive(Default)]
pub struct AppState {
    pub synthia_process: Mutex<Option<Child>>,
    /// Cached OAuth bearer token + the moment it was fetched.
    pub usage_cache: Mutex<Option<UsageTokenCache>>,
    /// Cached `UsageStats` response payload + fetch timestamp.
    pub usage_response_cache: Mutex<Option<UsageResponseCache>>,
    /// Filesystem watchers kept alive for the app lifetime; populated in CP9.
    #[allow(dead_code)] // wired up in CP9
    pub watchers: Mutex<Vec<Box<dyn std::any::Any + Send + Sync>>>,
    /// PTY session registry; read via `terminal_*` commands starting in Task 3.
    #[allow(dead_code)] // wired up in commands/terminal.rs
    pub terminals: TerminalRegistry,
    /// Native-embed (fake-embed) Wezterm sessions, keyed by UUID string.
    pub native_terminals: NativeTermRegistry,
}

#[derive(Clone, Debug)]
pub struct UsageTokenCache {
    pub token: String,
    pub fetched_at: Instant,
}

#[derive(Clone, Debug)]
pub struct UsageResponseCache {
    pub stats: UsageStats,
    pub fetched_at: Instant,
}

#[derive(Clone, Debug, Serialize)]
pub struct SessionMeta {
    pub id: Uuid,
    pub cwd: String,
    pub shell: String,
    pub title: String,
    pub created_at: DateTime<Utc>,
}

#[allow(dead_code)]
pub struct PtySession {
    pub master: Box<dyn MasterPty + Send>,
    pub writer: Box<dyn std::io::Write + Send>,
    pub child: Box<dyn PtyChild + Send + Sync>,
    /// Reader task starts in `terminal_attach`, not `terminal_spawn` —
    /// avoids a race where bash's first prompt is emitted before React
    /// subscribes to `terminal-output-{id}`.
    pub reader_task: Option<JoinHandle<()>>,
    /// Reader handle stored until `terminal_attach` consumes it.
    pub pending_reader: Option<Box<dyn std::io::Read + Send>>,
    pub meta: SessionMeta,
}

#[derive(Default)]
pub struct TerminalRegistry {
    pub sessions: Mutex<HashMap<Uuid, PtySession>>,
}

#[allow(dead_code)]
impl TerminalRegistry {
    pub fn list(&self) -> Vec<SessionMeta> {
        self.sessions.lock().values().map(|s| s.meta.clone()).collect()
    }
}

impl Drop for TerminalRegistry {
    fn drop(&mut self) {
        let mut guard = self.sessions.lock();
        for (_id, mut sess) in guard.drain() {
            let _ = sess.child.kill();
            if let Some(t) = sess.reader_task.take() {
                t.abort();
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_registry_starts_empty() {
        let reg = TerminalRegistry::default();
        let metas = reg.list();
        assert!(metas.is_empty());
    }
}
