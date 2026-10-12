import { useCallback, useEffect, useState } from "react";
import { formatSince, statusColor, statusLabel } from "./format";
import { call, reasonOf } from "./tauri";
import type { BrainView } from "./brain";
import { Engineering } from "./Engineering";
import { JobPanel } from "./JobPanel";
import { RolePanel } from "./RolePanel";
import { modelName, type Fleet, type FleetNode, type JobInfo, type RoleInfo, type SquadInfo } from "./types";

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

export const shortModel = modelName;

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
      className={`role${lead ? " lit" : " dim"}${selected ? " selected" : ""}`}
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

function Jobs({ jobs, now, selected, onPick }: { jobs: JobInfo[]; now: number; selected: string | null; onPick: (id: string) => void }) {
  if (jobs.length === 0) return <p className="co-quiet">No jobs yet.</p>;
  return (
    <ul className="jobs">
      {jobs.map((j) => (
        <li key={j.id}>
          <button type="button" className={j.id === selected ? "on" : ""} onClick={() => onPick(j.id)} aria-label={`Open job ${j.id}`}>
            <span className={`job-state s-${j.state}`}>{j.state}</span>
            <div>
              <b>{j.id}</b>
              {j.lastLog && <span>{j.lastLog}</span>}
            </div>
            <time>{j.updatedMs > 0 ? formatSince(j.updatedMs, now) : ""}</time>
          </button>
        </li>
      ))}
    </ul>
  );
}

function StartJob({ squad, onStarted }: { squad: SquadInfo; onStarted: () => void }) {
  const [open, setOpen] = useState(false);
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = () => {
    setBusy(true);
    setErr(null);
    call("squad_start_job", { squad: squad.id, brief })
      .then(() => {
        setOpen(false);
        setBrief("");
        onStarted();
      })
      .catch((e) => setErr(reasonOf(e)))
      .finally(() => setBusy(false));
  };
  if (!open) {
    return (
      <button type="button" className="ghost" onClick={() => setOpen(true)}>
        Start a job
      </button>
    );
  }
  return (
    <div className="start-box">
      <label className="lbl" htmlFor={`brief-${squad.id}`}>WHAT SHOULD THE {squad.name.toUpperCase()} SQUAD DO?</label>
      <textarea
        id={`brief-${squad.id}`}
        autoFocus
        value={brief}
        placeholder="Write the brief: the goal, who it is for, anything to avoid."
        onChange={(e) => setBrief(e.target.value)}
      />
      {err && <p className="co-error" role="status">{err}</p>}
      <div className="co-actions">
        <button type="button" className="primary" disabled={busy || brief.trim() === ""} onClick={go}>
          {busy ? "Starting…" : "Start"}
        </button>
        <button type="button" className="ghost" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  );
}

type Pick = { kind: "role"; squad: string; role: string } | { kind: "job"; squad: string; job: string };

/** A collapsible department: a header with its counts, then whatever it holds. */
function Dept({ name, counts, children }: { name: string; counts: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="dept" aria-label={name}>
      <button type="button" className="dept-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 10 10" aria-hidden="true" className={open ? "open" : ""}>
          <path d="M3 2l4 3-4 3" />
        </svg>
        <h2>{name}</h2>
        <span>{counts}</span>
      </button>
      {open && <div className="dept-body">{children}</div>}
    </section>
  );
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Mark at the top, Synthia beneath as chief of staff. */
function Leadership({ brain, fleet }: { brain: BrainView; fleet: Fleet | null }) {
  const nodes = fleet?.nodes ?? [];
  const working = nodes.filter((n) => n.status === "working").length;
  const line =
    brain.link !== "online"
      ? "Her brain is not connected."
      : brain.state === "thinking"
        ? "Thinking it over…"
        : brain.state === "speaking"
          ? brain.spoken.text.slice(0, 120) || "Speaking."
          : working > 0
            ? `Standing by · ${plural(working, "agent")} working`
            : "Standing by";
  return (
    <div className="leaders">
      <div className="boss">
        <b>Mark</b>
        <span>Owner</span>
      </div>
      <i className="drop" />
      <div className={`chief ${brain.link === "online" ? brain.state : "off"}`}>
        <span className="chief-dot" />
        <div>
          <b>Synthia</b>
          <span className="chief-role">Chief of staff</span>
          <p>{line}</p>
        </div>
      </div>
      <i className="drop" />
    </div>
  );
}

export function CompanyView({
  fleet,
  now,
  onFocus,
  request,
  brain,
}: {
  fleet: Fleet | null;
  now: number;
  onFocus: (paneId: string) => void;
  /** A job to open (from the constellation). `n` changes on every request. */
  request: { squad: string; job: string; n: number } | null;
  brain: BrainView;
}) {
  const [load, reload] = useSquads();
  const [pick, setPick] = useState<Pick | null>(null);
  const [seen, setSeen] = useState(0);
  if (request && request.n !== seen) {
    setSeen(request.n);
    setPick({ kind: "job", squad: request.squad, job: request.job });
  }
  const squads = load.status === "ready" ? load.squads : [];
  const pickedSquad = pick ? squads.find((s) => s.id === pick.squad) : undefined;
  const pickedRole = pick?.kind === "role" ? pickedSquad?.roles.find((r) => r.id === pick.role) : undefined;
  const panel = pick !== null && pickedSquad !== undefined && (pick.kind === "job" || pickedRole !== undefined);

  const note =
    load.status === "loading"
      ? "Reading your squads…"
      : load.status === "error"
        ? `I can't read your squads: ${load.reason}`
        : null;

  return (
    <section className={`company${panel ? " editing" : ""}`} aria-label="Your organisation">
      <div className="co-scroll">
        <Leadership brain={brain} fleet={fleet} />
        <div className="depts">
          <Engineering fleet={fleet} now={now} onFocus={onFocus} Dept={Dept} />
          {squads.map((squad) => {
            const { director, team } = chartRows(squad);
            const roles = new Map(squad.roles.map((r) => [r.id, r]));
            const members = (fleet?.nodes ?? []).filter((n) => n.squad === squad.id && n.status !== "gone");
            const working = members.filter((n) => n.status === "working").length;
            const card = (r: RoleInfo) => (
              <RoleCard
                key={r.id}
                squad={squad.id}
                role={r}
                roles={roles}
                live={liveFor(fleet, squad.id, r.id)}
                now={now}
                selected={pick?.kind === "role" && pick.squad === squad.id && pick.role === r.id}
                onPick={() => setPick({ kind: "role", squad: squad.id, role: r.id })}
              />
            );
            return (
              <Dept
                key={squad.id}
                name={squad.name}
                counts={members.length === 0 ? "no live job" : `${working} working · ${plural(members.length, "member")}`}
              >
                <p className="dept-sub">
                  up to {squad.cap} at once{squad.cwd ? ` · ${squad.cwd}` : ""}
                </p>
                <div className="org">
                  <div className="org-inner">
                    {director && <div className="org-top">{card(director)}</div>}
                    {team.length > 0 && (
                      <div className={`org-team${director ? " under" : ""}`} style={{ ["--n" as string]: team.length }}>
                        {team.map(card)}
                      </div>
                    )}
                  </div>
                </div>
                <div className="jobs-head">
                  <h3 className="lbl">RECENT JOBS</h3>
                  <StartJob squad={squad} onStarted={reload} />
                </div>
                <Jobs
                  jobs={squad.jobs}
                  now={now}
                  selected={pick?.kind === "job" && pick.squad === squad.id ? pick.job : null}
                  onPick={(job) => setPick({ kind: "job", squad: squad.id, job })}
                />
              </Dept>
            );
          })}
        </div>
        {note && <p className={`co-quiet${load.status === "error" ? " co-error" : ""}`} role="status">{note}</p>}
        {load.status === "ready" && squads.length === 0 && (
          <p className="co-quiet" role="status">
            No squads yet. Run <code>synthia-squad install growth</code> in a terminal and your first team appears here.
          </p>
        )}
      </div>
      {panel && pick.kind === "role" && pickedSquad && pickedRole && (
        <RolePanel
          key={`${pick.squad}/${pick.role}`}
          squad={pickedSquad}
          role={pickedRole}
          live={liveFor(fleet, pickedSquad.id, pickedRole.id)}
          onClose={() => setPick(null)}
          onSaved={reload}
          onFocus={onFocus}
        />
      )}
      {panel && pick.kind === "job" && pickedSquad && (
        <JobPanel
          key={`${pick.squad}/${pick.job}`}
          squad={pickedSquad}
          jobId={pick.job}
          fleet={fleet}
          now={now}
          onClose={() => setPick(null)}
          onFocus={onFocus}
        />
      )}
    </section>
  );
}
