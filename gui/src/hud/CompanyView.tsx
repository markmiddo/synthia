import { useCallback, useEffect, useMemo, useState } from "react";
import { formatSince, statusColor, statusLabel } from "./format";
import { call, reasonOf } from "./tauri";
import { MODELS, type Fleet, type FleetNode, type JobInfo, type RoleFields, type RoleInfo, type SquadInfo } from "./types";

const REFRESH_MS = 5000;

type Load = { status: "loading" } | { status: "ready"; squads: SquadInfo[] } | { status: "error"; reason: string };

function useSquads(): [Load, () => void] {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const reload = useCallback(() => {
    call<SquadInfo[]>("squads_list")
      .then((squads) => setLoad({ status: "ready", squads }))
      .catch((e) => setLoad((prev) => (prev.status === "ready" ? prev : { status: "error", reason: reasonOf(e) })));
  }, []);
  useEffect(() => {
    reload();
    const t = setInterval(reload, REFRESH_MS);
    return () => clearInterval(t);
  }, [reload]);
  return [load, reload];
}

export function shortModel(model: string): string {
  const m = model.replace(/^claude-/, "").replace(/-\d+(-\d+)*$/, "");
  return m || model || "no model";
}

/** Roles in chart order: the director, then everyone it hires (in order), then anyone left over. */
export function chartRows(squad: SquadInfo): { director: RoleInfo | null; team: RoleInfo[] } {
  const byId = new Map(squad.roles.map((r) => [r.id, r]));
  const director = byId.get(squad.director) ?? null;
  const seen = new Set<string>(director ? [director.id] : []);
  const team: RoleInfo[] = [];
  for (const id of director?.hires ?? []) {
    const r = byId.get(id);
    if (r && !seen.has(id)) {
      seen.add(id);
      team.push(r);
    }
  }
  for (const r of squad.roles) {
    if (!seen.has(r.id)) {
      seen.add(r.id);
      team.push(r);
    }
  }
  return { director, team };
}

function liveFor(fleet: Fleet | null, squad: string, role: string): FleetNode[] {
  return (fleet?.nodes ?? []).filter((n) => n.squad === squad && n.role === role && n.status !== "gone");
}

function RoleCard({
  squad,
  role,
  roles,
  live,
  now,
  selected,
  onPick,
}: {
  squad: string;
  role: RoleInfo;
  roles: Map<string, RoleInfo>;
  live: FleetNode[];
  now: number;
  selected: boolean;
  onPick: () => void;
}) {
  const lead = live.find((n) => n.status === "working" || n.status === "needs-you") ?? live[0];
  const color = lead ? statusColor(lead.status) : "var(--slate)";
  return (
    <button
      type="button"
      className={`role${lead ? " lit" : ""}${selected ? " selected" : ""}`}
      style={{ ["--c" as string]: color }}
      onClick={onPick}
      aria-label={`Edit ${role.title || role.id} in the ${squad} squad`}
    >
      <span className="role-dot" />
      <b>{role.title || role.id}</b>
      <span className="role-meta">
        <span className="chip">{shortModel(role.model)}</span>
        {lead && (
          <em>
            {statusLabel(lead.status, lead.sinceMs, now)}
            {live.length > 1 ? ` · ${live.length} running` : ""}
          </em>
        )}
      </span>
      {role.hires.length > 0 && (
        <span className="role-hires">
          hires {role.hires.map((h) => roles.get(h)?.title || h).join(", ")}
        </span>
      )}
    </button>
  );
}

function Jobs({ jobs, now }: { jobs: JobInfo[]; now: number }) {
  const [err, setErr] = useState<string | null>(null);
  if (jobs.length === 0) return <p className="co-quiet">No jobs yet.</p>;
  return (
    <>
      <ul className="jobs">
        {jobs.map((j) => (
          <li key={j.id}>
            <span className={`job-state s-${j.state}`}>{j.state}</span>
            <div>
              <b>{j.id}</b>
              {j.lastLog && <span>{j.lastLog}</span>}
            </div>
            <time>{j.updatedMs > 0 ? formatSince(j.updatedMs, now) : ""}</time>
            <button
              type="button"
              className="link-btn"
              onClick={() =>
                call("squad_open_job", { path: j.path })
                  .then(() => setErr(null))
                  .catch((e) => setErr(`I couldn't open that folder: ${reasonOf(e)}`))
              }
            >
              Open folder
            </button>
          </li>
        ))}
      </ul>
      {err && <p className="co-error">{err}</p>}
    </>
  );
}

function EditPanel({
  squad,
  role,
  live,
  onClose,
  onSaved,
  onFocus,
}: {
  squad: SquadInfo;
  role: RoleInfo;
  live: FleetNode[];
  onClose: () => void;
  onSaved: () => void;
  onFocus: (paneId: string) => void;
}) {
  const [title, setTitle] = useState(role.title);
  const [model, setModel] = useState(role.model);
  const [prompt, setPrompt] = useState(role.prompt);
  const [hires, setHires] = useState(role.hires);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const isDirector = role.id === squad.director;
  const others = squad.roles.filter((r) => r.id !== role.id);
  const modelOptions = (MODELS as readonly string[]).includes(model) || !model ? MODELS : [model, ...MODELS];

  const dirty =
    title !== role.title || model !== role.model || prompt !== role.prompt || hires.join() !== role.hires.join();

  const save = () => {
    const fields: RoleFields = {};
    if (title !== role.title) fields.title = title;
    if (model !== role.model) fields.model = model;
    if (prompt !== role.prompt) fields.prompt = prompt;
    if (hires.join() !== role.hires.join()) fields.hires = hires;
    setBusy(true);
    setMsg(null);
    call("squad_role_save", { squad: squad.id, role: role.id, fields })
      .then(() => {
        setMsg({ ok: true, text: "Saved. New hires use this from now on." });
        onSaved();
      })
      .catch((e) => setMsg({ ok: false, text: `I couldn't save that: ${reasonOf(e)}` }))
      .finally(() => setBusy(false));
  };

  return (
    <aside className="co-panel" aria-label={`Edit ${role.title || role.id}`}>
      <div className="co-panel-head">
        <div>
          <p className="lbl">{squad.name.toUpperCase()} · {role.id}</p>
          <h2>{role.title || role.id}</h2>
        </div>
        <button type="button" className="link-btn" onClick={onClose} aria-label="Close editor">
          Close
        </button>
      </div>
      {live.length > 0 && (
        <p className="co-live">
          {live.length} running now.{" "}
          <button type="button" className="link-btn" onClick={() => onFocus(live[0].paneId)}>
            Go to its pane
          </button>
        </p>
      )}
      <label>
        Title
        <input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label>
        Model
        <select value={model} onChange={(e) => setModel(e.target.value)}>
          {modelOptions.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      {isDirector && others.length > 0 && (
        <fieldset>
          <legend>Hires</legend>
          {others.map((r) => (
            <label key={r.id} className="check">
              <input
                type="checkbox"
                checked={hires.includes(r.id)}
                onChange={(e) =>
                  setHires((h) => (e.target.checked ? [...h, r.id] : h.filter((x) => x !== r.id)))
                }
              />
              {r.title || r.id}
            </label>
          ))}
        </fieldset>
      )}
      <label className="grow">
        Prompt
        <textarea value={prompt} spellCheck={false} onChange={(e) => setPrompt(e.target.value)} />
      </label>
      {!role.hasAgentFile && (
        <p className="co-quiet">This role has no agent file yet. Saving a prompt creates one.</p>
      )}
      <div className="co-actions">
        <button type="button" className="primary" disabled={busy || !dirty || title.trim() === ""} onClick={save}>
          {busy ? "Saving…" : "Save"}
        </button>
        {msg && <span className={msg.ok ? "co-ok" : "co-error"}>{msg.text}</span>}
      </div>
    </aside>
  );
}

export function CompanyView({
  fleet,
  now,
  onFocus,
}: {
  fleet: Fleet | null;
  now: number;
  onFocus: (paneId: string) => void;
}) {
  const [load, reload] = useSquads();
  const [pick, setPick] = useState<{ squad: string; role: string } | null>(null);
  const squads = load.status === "ready" ? load.squads : [];

  const picked = useMemo(() => {
    if (!pick) return null;
    const squad = squads.find((s) => s.id === pick.squad);
    const role = squad?.roles.find((r) => r.id === pick.role);
    return squad && role ? { squad, role } : null;
  }, [pick, squads]);

  const note =
    load.status === "loading"
      ? "Reading your squads…"
      : load.status === "error"
        ? `I can't read your squads: ${load.reason}`
        : null;

  return (
    <section className={`company${picked ? " editing" : ""}`} aria-label="Your squads">
      <div className="co-scroll">
        {note && <p className={`co-quiet${load.status === "error" ? " co-error" : ""}`} role="status">{note}</p>}
        {load.status === "ready" && squads.length === 0 && (
          <p className="co-empty" role="status">
            No squads yet. Run <code>synthia-squad install growth</code> in a terminal and your first team appears here.
          </p>
        )}
        {squads.map((squad) => {
          const { director, team } = chartRows(squad);
          const roles = new Map(squad.roles.map((r) => [r.id, r]));
          const card = (r: RoleInfo) => (
            <RoleCard
              key={r.id}
              squad={squad.id}
              role={r}
              roles={roles}
              live={liveFor(fleet, squad.id, r.id)}
              now={now}
              selected={pick?.squad === squad.id && pick.role === r.id}
              onPick={() => setPick({ squad: squad.id, role: r.id })}
            />
          );
          return (
            <article key={squad.id} className="squad">
              <header>
                <h2>{squad.name}</h2>
                <span>
                  up to {squad.cap} at once{squad.cwd ? ` · ${squad.cwd}` : ""}
                </span>
              </header>
              <div className="org">
                {director && <div className="org-top">{card(director)}</div>}
                {team.length > 0 && <div className={`org-team${director ? " under" : ""}`}>{team.map(card)}</div>}
              </div>
              <h3 className="lbl">RECENT JOBS</h3>
              <Jobs jobs={squad.jobs} now={now} />
            </article>
          );
        })}
      </div>
      {picked && (
        <EditPanel
          key={`${picked.squad.id}/${picked.role.id}`}
          squad={picked.squad}
          role={picked.role}
          live={liveFor(fleet, picked.squad.id, picked.role.id)}
          onClose={() => setPick(null)}
          onSaved={reload}
          onFocus={onFocus}
        />
      )}
    </section>
  );
}
