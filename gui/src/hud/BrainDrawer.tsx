import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ago,
  KIND_BLURB,
  KIND_COLORS,
  type BrainNow,
  type BrainOverview,
  type Connected,
  type MemoryBody,
  type MemoryRow,
  type RecallEntry,
  type SkillsInfo,
} from "./hive";
import { Markdown } from "./markdown";
import { call, reasonOf } from "./tauri";

type Tab = "memory" | "now" | "recalls" | "skills" | "connected";

const TABS: [Tab, string][] = [
  ["memory", "Memories"],
  ["now", "Right now"],
  ["recalls", "Recalled today"],
  ["skills", "Skills and roles"],
  ["connected", "Connected"],
];

const GUARDRAILS =
  "Drafts only unless Mark approves. Spoken confirmation before a production promote, anything that moves money, or a message to customers or organisers.";

function startOfToday(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function Tile({ n, label }: { n: number | string; label: string }) {
  return (
    <div className="dtile">
      <b>{typeof n === "number" ? n.toLocaleString() : n}</b>
      <span>{label}</span>
    </div>
  );
}

function useLoaded<T>(cmd: string, args?: Record<string, unknown>): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  const key = JSON.stringify(args ?? {});
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, error: null }));
    call<T>(cmd, args)
      .then((d) => alive && setState({ data: d, error: null }))
      .catch((e) => alive && setState((s) => ({ ...s, error: reasonOf(e) })));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cmd, key]);
  return state;
}

function MemoryRowView({ row, now }: { row: MemoryRow; now: number }) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<MemoryBody | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !body) {
      call<MemoryBody>("brain_memory", { path: row.path })
        .then(setBody)
        .catch((e) => setErr(reasonOf(e)));
    }
  };
  const used = row.recalls7d > 0 ? `${row.recalls7d} this week` : `changed ${ago(row.modifiedMs, now)}`;
  return (
    <div className={`mrow${open ? " open" : ""}`}>
      <button type="button" className="mhead" aria-expanded={open} onClick={toggle}>
        <span className={`mkind k-${row.kind}`}>{row.kind}</span>
        <span className="t">
          {row.name}
          <small>
            {row.description.slice(0, 90)}
            {row.description.length > 90 ? "…" : ""}
          </small>
        </span>
        <span className="used">{used}</span>
      </button>
      {open && (
        <div className="mdetail">
          {err ? <p className="co-error">I couldn't read that memory: {err}</p> : body ? <Markdown text={body.body} /> : <p className="co-quiet">Reading…</p>}
          {row.teams7d.length > 0 && (
            <div className="by">
              <span className="co-quiet">Used this week by</span>
              {row.teams7d.map((t) => (
                <span key={t} className="hchip">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MemoriesTab({ overview, now }: { overview: BrainOverview; now: number }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 220);
    return () => clearTimeout(t);
  }, [q]);
  const { data: rows, error } = useLoaded<MemoryRow[]>("brain_memories", { query: debounced || null });
  const max = Math.max(1, ...overview.kinds.map((k) => k.count));
  const searching = debounced !== "";
  const shown = (rows ?? []).slice(0, searching ? 30 : 12);
  return (
    <>
      <div className="dtiles">
        <Tile n={overview.total} label="memories" />
        <Tile n={overview.recalledToday} label="recalled today" />
        <Tile n={overview.writtenToday} label="written today" />
        <Tile n={overview.vaultNotes} label="vault notes" />
      </div>
      <p className="dsec">What kind of thing she remembers</p>
      <div className="bars">
        {overview.kinds.map((k) => (
          <div className="brow" key={k.kind} title={KIND_BLURB[k.kind]}>
            <span>{k.kind[0].toUpperCase() + k.kind.slice(1)}</span>
            <div className="track">
              <div className="fill" style={{ width: `${(k.count / max) * 100}%`, background: KIND_COLORS[k.kind] ?? "var(--muted)" }} />
            </div>
            <span className="n">{k.count}</span>
          </div>
        ))}
      </div>
      <p className="dsec">{searching ? "Search results" : "Most used this week · click one to read it"}</p>
      <input className="dsearch" type="search" placeholder="Search every memory by name or description" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search memories" />
      {error && <p className="co-error">I couldn't read the memories: {error}</p>}
      <div className="mem">
        {shown.map((r) => (
          <MemoryRowView key={r.path} row={r} now={now} />
        ))}
        {rows !== null && shown.length === 0 && <p className="co-quiet">{searching ? "Nothing matches that." : "No memories found."}</p>}
      </div>
    </>
  );
}

function NowTab({ agents, brainState, brainOnline, now }: { agents: number; brainState: string; brainOnline: boolean; now: number }) {
  const { data, error } = useLoaded<BrainNow>("brain_now");
  const stateLabel = !brainOnline ? "Not connected" : brainState === "thinking" ? "Thinking" : brainState === "speaking" ? "Speaking" : "Standing by";
  return (
    <>
      <p className="dsec">Synthia right now</p>
      <div className="ctx">
        <div className="ctx-row">Her state<span>{stateLabel}</span></div>
        <div className="ctx-row">Live agents<span>{agents}</span></div>
        {data && (
          <>
            <div className="ctx-row">
              Session{data.sessionId ? ` ${data.sessionId.slice(0, 8)}` : ""}
              <span>
                {data.sessionDate ?? "none yet"}
                {data.sessionModifiedMs ? ` · updated ${ago(data.sessionModifiedMs, now)}` : ""}
              </span>
            </div>
            <div className="ctx-row">
              Ledger today
              <span>
                {data.ledgerDone} done · {data.ledgerCalls} calls · {data.ledgerWaiting} waiting on you
              </span>
            </div>
          </>
        )}
      </div>
      {error && <p className="co-error">I couldn't read her context: {error}</p>}
      <p className="dsec">{data?.journal ? `Latest journal · ${data.journal.name}` : "Latest journal"}</p>
      {data?.journal ? <pre className="journal">{data.journal.text}</pre> : <p className="co-quiet">No journal entries yet.</p>}
    </>
  );
}

function RecallsTab() {
  const since = useMemo(() => startOfToday(), []);
  const { data, error } = useLoaded<RecallEntry[]>("brain_recalls", { since });
  const rows = (data ?? []).slice().reverse();
  return (
    <>
      <p className="dsec">Who reached into the brain today</p>
      {error && <p className="co-error">I couldn't read the recall log: {error}</p>}
      {data !== null && rows.length === 0 && (
        <p className="co-quiet">Nothing recalled yet today. Recalls appear here once the memory hook is registered and a session reads a memory.</p>
      )}
      <div className="feedl">
        {rows.map((r, i) => (
          <div className="fl" key={`${r.atMs}-${i}`}>
            <time>{clock(r.atMs)}</time>
            <span className="fdot" style={{ background: r.kind === "write" ? "var(--amber)" : "var(--blue)" }} />
            <span className="what">
              <b>{r.team.label}</b> · {r.title} <span>· {r.kind === "write" ? "wrote" : "read"}</span>
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

function SkillsTab() {
  const { data, error } = useLoaded<SkillsInfo>("brain_skills");
  const [q, setQ] = useState("");
  const list = (data?.skills ?? []).filter((s) => {
    const k = q.trim().toLowerCase();
    return !k || s.name.toLowerCase().includes(k) || s.description.toLowerCase().includes(k);
  });
  return (
    <>
      {error && <p className="co-error">I couldn't read the skills: {error}</p>}
      <div className="dtiles">
        <Tile n={data?.skills.length ?? 0} label="skills" />
        <Tile n={data?.roles.length ?? 0} label="roles" />
        <Tile n={data?.claudeMd ?? 0} label="CLAUDE.md handbooks" />
        <Tile n={data?.squads ?? 0} label="squads" />
      </div>
      <p className="dsec">Skills the teams can use</p>
      <input className="dsearch" type="search" placeholder="Search skills" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search skills" />
      <div className="mem">
        {list.slice(0, 40).map((s) => (
          <div className="mrow plain" key={s.name}>
            <span className="mkind k-skill">skill</span>
            <span className="t">
              {s.name}
              <small>{s.description.slice(0, 110)}{s.description.length > 110 ? "…" : ""}</small>
            </span>
            <span />
          </div>
        ))}
        {list.length > 40 && <p className="co-quiet">+{list.length - 40} more. Search to narrow it down.</p>}
      </div>
      <p className="dsec">Roles on the team</p>
      <div className="who">
        {(data?.roles ?? []).map((r) => (
          <span key={r} className="hchip">
            {r}
          </span>
        ))}
      </div>
    </>
  );
}

function ConnectedTab() {
  const { data, error } = useLoaded<Connected>("brain_connected");
  return (
    <>
      {error && <p className="co-error">I couldn't read the connections: {error}</p>}
      <p className="dsec">Tools on this machine</p>
      <div className="conn">
        {(data?.local ?? []).map((n) => (
          <div key={n}>{n}</div>
        ))}
        {data && data.local.length === 0 && <p className="co-quiet">None found.</p>}
      </div>
      {data && data.claudeAi.length > 0 && (
        <>
          <p className="dsec">claude.ai connectors</p>
          <div className="conn">
            {data.claudeAi.map((n) => (
              <div key={n}>{n}</div>
            ))}
          </div>
        </>
      )}
      <p className="dsec">Guardrails shared by everyone</p>
      <div className="mdetail solo">{GUARDRAILS}</div>
    </>
  );
}

export function BrainDrawer({
  overview,
  agents,
  brainState,
  brainOnline,
  onClose,
}: {
  overview: BrainOverview;
  agents: number;
  brainState: string;
  brainOnline: boolean;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("memory");
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const now = Date.now();
  useEffect(() => {
    closeRef.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  // Portalled to the page root so no panel's stacking context can sit above it.
  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" aria-label="Inside the brain">
        <div className="dhead">
          <div>
            <p className="eyebrow">Inside the brain</p>
            <h2>Everything the teams share</h2>
            <p className="dsub">What Synthia and every squad can draw on: memories, skills, the team handbook, today's live context and connected tools.</p>
          </div>
          <button type="button" ref={closeRef} className="icon-btn" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" />
            </svg>
          </button>
        </div>
        <nav className="dtabs" role="tablist">
          {TABS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="dbody">
          {tab === "memory" && <MemoriesTab overview={overview} now={now} />}
          {tab === "now" && <NowTab agents={agents} brainState={brainState} brainOnline={brainOnline} now={now} />}
          {tab === "recalls" && <RecallsTab />}
          {tab === "skills" && <SkillsTab />}
          {tab === "connected" && <ConnectedTab />}
        </div>
      </aside>
    </>,
    document.body,
  );
}
