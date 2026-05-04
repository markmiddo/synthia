# AI Security Noise Reduction — Design

**Date:** 2026-05-04
**Branch:** `feat/ai-security-noise-reduction`
**Scope:** `gui/src-tauri/src/egress.rs` + `commands/neuralguard.rs` + `gui/src/App.tsx` (Security section)

## Problem

Egress monitor produces 28+ "Outbound connection to unrecognised host" events per session because the allowlist resolves canonical hosts (`api.anthropic.com`, `claude.ai`) at startup but Anthropic serves traffic from rotating Google Cloud / Cloudflare front-end IPs that don't match. Result: a wall of identical-looking medium-severity events that obscure any real signal. User reaction: "looks messy, I don't know what's going on."

## Goals

1. Cut false positives drastically by trusting cloud-provider CIDR ranges + reverse-DNS-resolved hostnames.
2. Group identical events in the GUI so 28 dupes show as one row with `(×28)` badge.
3. Default the severity tab to "High & above" when any HIGH+ exists, falling back to "All" only when there's nothing important.
4. Give the user a one-click "Allow host" button to silence repeat false positives without editing config files.

## Non-goals

- Allowlist removal UI (manual YAML edit for now)
- Wildcard support in user allowlist (`*.example.com`)
- Per-event "Block" button or always-deny rules
- Egress monitoring of non-AI processes
- Backend event-row dedupe (preserve audit log fidelity in `events.jsonl`)

## Architecture

### 1. Smarter egress detection (`gui/src-tauri/src/egress.rs`)

Three-layer verdict on each peer IP, fall through:

**Layer 1 — Static cloud-provider CIDRs.** Hardcoded list of well-known ranges:

```rust
const CLOUD_CIDRS: &[(&str, &str)] = &[
    ("8.8.0.0/16",        "Google"),
    ("8.34.208.0/20",     "Google"),
    ("8.35.192.0/20",     "Google"),
    ("34.0.0.0/9",        "Google Cloud"),
    ("34.128.0.0/10",     "Google Cloud"),
    ("35.184.0.0/13",     "Google Cloud"),
    ("35.190.0.0/16",     "Google"),
    ("35.191.0.0/16",     "Google"),
    ("35.192.0.0/14",     "Google Cloud"),
    ("104.16.0.0/12",     "Cloudflare"),
    ("172.64.0.0/13",     "Cloudflare"),
    ("13.32.0.0/15",      "AWS CloudFront"),
    ("13.224.0.0/14",     "AWS CloudFront"),
    ("52.84.0.0/15",      "AWS CloudFront"),
    ("99.84.0.0/16",      "AWS CloudFront"),
    ("3.5.0.0/16",        "AWS S3"),
    ("52.216.0.0/15",     "AWS S3"),
    ("20.0.0.0/8",        "Azure"),
    ("40.64.0.0/10",      "Azure"),
    ("160.79.104.0/23",   "Anthropic"),
];
```

Match → record verdict `Allowed("Google Cloud")` and skip event emission.

**Layer 2 — Reverse DNS.** On CIDR miss, call `std::net::lookup_addr(&ip)` (returns hostname). If it ends with one of:

```rust
const TRUSTED_PTR_SUFFIXES: &[&str] = &[
    ".googleusercontent.com",
    ".1e100.net",            // Google
    ".amazonaws.com",
    ".cloudfront.net",
    ".cloudflare.com",
    ".anthropic.com",
    ".openai.com",
    ".github.com",
    ".github.io",
];
```

→ verdict `Allowed("PTR: <hostname>")`.

**Layer 3 — User allowlist.** Read `~/.config/synthia/security/allowlist.yaml`:

```yaml
hosts:
  - special-internal-api.com
  - my-self-hosted.local
ips:
  - 10.0.0.42
```

Re-resolve `hosts` to IPs at allowlist-load time (1h TTL like the default allowlist). If peer IP matches an `ips` entry literally or matches a resolved `hosts` IP → `Allowed("user-allowlist")`.

**Verdict cache.** `Mutex<HashMap<IpAddr, (Verdict, Instant)>>`, 1h TTL. Caches both `Allowed(...)` and `Unknown` so we don't re-PTR-lookup every 30s poll cycle.

**Event emission.** Only `Unknown` verdicts produce a `RuleHit` (and thus a SecurityEvent). Allowed connections produce no event.

### 2. Event grouping in the GUI (`gui/src/App.tsx::renderSecuritySection`)

Frontend-only — backend `events.jsonl` continues writing one row per event for audit fidelity.

Group key = `${rule}::${agent_pid_or_kind}::${dest_ip_or_host}`.

```tsx
type EventGroup = {
  key: string;
  events: SecurityEvent[];
  latest: SecurityEvent;
};

function groupEvents(events: SecurityEvent[]): EventGroup[] {
  const groups = new Map<string, SecurityEvent[]>();
  for (const e of events) {
    const ipMatch = e.matched.match(/^([\d.:a-f]+)/);
    const dest = ipMatch ? ipMatch[1] : e.matched;
    const proc = e.agent_pid?.toString() ?? e.agent_kind ?? "?";
    const key = `${e.rule}::${proc}::${dest}`;
    const arr = groups.get(key) ?? [];
    arr.push(e);
    groups.set(key, arr);
  }
  return [...groups.entries()]
    .map(([key, evts]) => ({
      key,
      events: evts.sort((a, b) => b.ts.localeCompare(a.ts)),
      latest: evts[0],
    }))
    .sort((a, b) => b.latest.ts.localeCompare(a.latest.ts));
}
```

Render: one card per group. Header shows `latest.ts` + `(×N)` badge if N>1. Default collapsed. Click expands → vertical list of all instances with individual timestamps, hidden behind a `<details>` element.

### 3. Smart default tab

```tsx
const [filterTab, setFilterTab] = useState<"all" | "high">("all");
const [tabAutoChosen, setTabAutoChosen] = useState(false);

useEffect(() => {
  if (tabAutoChosen || events.length === 0) return;
  const hasHigh = events.some(
    e => e.severity === "high" || e.severity === "critical"
  );
  setFilterTab(hasHigh ? "high" : "all");
  setTabAutoChosen(true);
}, [events, tabAutoChosen]);
```

Auto-pick fires once on first event load, then locked — user clicks override. Resets when section is re-mounted (no persistence beyond session).

### 4. One-click allowlist

New Tauri command in `commands/neuralguard.rs`:

```rust
#[tauri::command]
pub fn add_to_allowlist(host: String) -> AppResult<()> {
    if host.is_empty() || host.contains('/') || host.contains(' ') || host.len() > 253 {
        return Err(AppError::Validation(format!("bad host: {host}")));
    }
    let path = security_dir().join("allowlist.yaml");
    std::fs::create_dir_all(security_dir())?;
    let existing = std::fs::read_to_string(&path).unwrap_or_default();
    let new_content = crate::yaml_writer::append_allowlist_host(&existing, &host);
    std::fs::write(&path, new_content)?;
    crate::egress::invalidate_allowlist_cache();
    Ok(())
}
```

`yaml_writer::append_allowlist_host`:
- Parses existing file (or creates skeleton).
- If `host` already in `hosts:` list → no-op.
- Otherwise appends `  - <host>` under the `hosts:` section. Comments + other sections preserved.

`egress::invalidate_allowlist_cache()` clears the user-allowlist verdict cache so next poll picks up the new entry.

GUI button: per-event, only shown for `rule == "egress-unknown-host"`. Label: `Allow host`. Tooltip: "Add to your egress allowlist". On click → resolve hostname (PTR if available, else `ip:port`) → `invoke('add_to_allowlist', { host })` → toast `Allowed <host>`.

## Files touched

| File | Change |
|---|---|
| `gui/src-tauri/Cargo.toml` | Add `ipnet = "2"` |
| `gui/src-tauri/src/egress.rs` | CIDR ranges, PTR lookup, verdict cache, user allowlist read, `invalidate_allowlist_cache()` |
| `gui/src-tauri/src/commands/neuralguard.rs` | `add_to_allowlist` command |
| `gui/src-tauri/src/lib.rs` | Register `add_to_allowlist` in `generate_handler!` |
| `gui/src-tauri/src/yaml_writer.rs` | `append_allowlist_host` writer + tests |
| `gui/src-tauri/src/config.rs` | `UserAllowlist { hosts, ips }` struct |
| `gui/src/App.tsx` | `groupEvents`, render groups, smart default tab, "Allow host" button + handler |
| `gui/src/App.css` | Group card collapse, count badge styling |

## Tests

- `egress::tests::cidr_matches_google_range` — `35.190.46.17` ∈ `35.190.0.0/16`
- `egress::tests::cidr_misses_unrelated` — `1.2.3.4` ∉ all ranges
- `egress::tests::trusted_ptr_suffix_matches` — `host.googleusercontent.com` allowed
- `egress::tests::cache_returns_within_ttl` — second lookup of same IP doesn't re-resolve
- `egress::tests::cache_expires_after_ttl` — synthetic time advance
- `config::tests::user_allowlist_round_trip`
- `yaml_writer::tests::append_allowlist_host_creates_section_if_missing`
- `yaml_writer::tests::append_allowlist_host_preserves_comments`
- `yaml_writer::tests::append_allowlist_host_skips_duplicates`
- `commands::neuralguard::tests::add_to_allowlist_rejects_bad_host`
- `commands::neuralguard::tests::add_to_allowlist_accepts_normal_host`

GUI grouping + smart-default-tab logic: manual smoke (no React test framework in repo currently).

## Migration

- New file: `~/.config/synthia/security/allowlist.yaml` — created on first "Allow host" click. No migration required.
- Existing `events.jsonl` rows from before this change still display correctly (grouping operates on whatever the backend already wrote).

## Risks

- **CIDR ranges go stale.** Cloud providers expand IP space. Mitigation: PTR fallback catches IPs in newly-added ranges that still resolve to a trusted suffix.
- **PTR lookup can be slow** (DNS roundtrip). Mitigation: 1h verdict cache; lookup happens on poll thread, not on UI thread.
- **`lookup_addr` not in stable std.** Stable since Rust 1.0 actually, but only `std::net::ToSocketAddrs` is well-known. Use `dns_lookup` crate or shell out to `getent hosts`. Decision: use `dns_lookup = "2"` (3kB, well-maintained, no transitive bloat).
- **User allowlist edits race with cache.** `invalidate_allowlist_cache()` after every write keeps it consistent.
- **Event grouping hides timing patterns.** A flood of 100 events to one IP looks the same as 2. Mitigation: count badge makes the magnitude obvious; expand to see individual timestamps.

## Verification matrix

| Concern | How verified |
|---|---|
| False positives drop | Manual: enable egress, run a session, verify 28 → ~0 unknown-host events |
| Cache hit rate | Add a debug log line in egress on cache hit/miss; observe ratio |
| Grouping correct | Manual: trigger 5 events to same IP, see one card `(×5)` |
| Smart default tab | Manual: with no HIGH events → "All" tab; trigger HIGH → "High & above" |
| Allow-host button works | Manual: click → check `~/.config/synthia/security/allowlist.yaml` updated; next poll skips that host |
| Audit log unchanged | `events.jsonl` still records every individual event |

## Out of scope (deferred)

- GUI Allowlist tab (view/remove user-allowed entries)
- Wildcard host patterns in user allowlist
- "Block forever" option per event
- Per-process allowlist scoping
- Mass-allow ("trust this entire CIDR range") UI
