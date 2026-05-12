//! Tauri-managed application state, replacing static `Mutex<Option<T>>` globals.

use std::collections::HashMap;
use std::process::Child;
use std::sync::Mutex;
use std::time::Instant;

use chrono::{DateTime, Utc};
use portable_pty::{Child as PtyChild, MasterPty};
use serde::Serialize;
use tokio::task::JoinHandle;
use uuid::Uuid;

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
    /// Kept alive for custom Drop impl; manages PTY session lifecycle.
    #[allow(dead_code)]
    pub terminals: TerminalRegistry,
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
    pub reader_task: JoinHandle<()>,
    pub meta: SessionMeta,
}

#[derive(Default)]
pub struct TerminalRegistry {
    pub sessions: Mutex<HashMap<Uuid, PtySession>>,
}

#[allow(dead_code)]
impl TerminalRegistry {
    pub fn list(&self) -> Vec<SessionMeta> {
        match self.sessions.lock() {
            Ok(g) => g.values().map(|s| s.meta.clone()).collect(),
            Err(_) => Vec::new(),
        }
    }
}

impl Drop for TerminalRegistry {
    fn drop(&mut self) {
        let mut guard = match self.sessions.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        for (_id, mut sess) in guard.drain() {
            let _ = sess.child.kill();
            sess.reader_task.abort();
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
