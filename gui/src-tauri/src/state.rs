//! Tauri-managed application state, replacing static `Mutex<Option<T>>` globals.

use std::process::Child;
use std::sync::Mutex;
use std::time::Instant;

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
