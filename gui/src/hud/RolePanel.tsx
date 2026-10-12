import { useState } from "react";
import { Markdown } from "./markdown";
import { call, reasonOf } from "./tauri";
import { MODEL_CHOICES, modelName, type FleetNode, type RoleFields, type RoleInfo, type SquadInfo } from "./types";

export function CloseButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button type="button" className="icon-btn" onClick={onClick} aria-label={label} title={label}>
      <svg viewBox="0 0 12 12" aria-hidden="true">
        <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" />
      </svg>
    </button>
  );
}

export function RolePanel({
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
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const isDirector = role.id === squad.director;
  const others = squad.roles.filter((r) => r.id !== role.id);
  const choices = MODEL_CHOICES.some((m) => m.id === model) || !model ? MODEL_CHOICES : [{ id: model, name: modelName(model) }, ...MODEL_CHOICES];
  const dirty = title !== role.title || model !== role.model || prompt !== role.prompt || hires.join() !== role.hires.join();

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
        setMsg({ ok: true, text: "Saved" });
        setEditing(false);
        onSaved();
      })
      .catch((e) => setMsg({ ok: false, text: `I couldn't save that: ${reasonOf(e)}` }))
      .finally(() => setBusy(false));
  };

  return (
    <aside className="co-panel" aria-label={`Edit ${role.title || role.id}`}>
      <div className="co-panel-head">
        <div>
          <p className="lbl">{squad.name.toUpperCase()} SQUAD</p>
          <h2>{role.title || role.id}</h2>
        </div>
        <CloseButton onClick={onClose} label="Close editor" />
      </div>
      {live.length > 0 && (
        <p className="co-live">
          {live.length} running now ·{" "}
          <button type="button" className="link-btn" onClick={() => onFocus(live[0].paneId)}>
            Watch
          </button>
        </p>
      )}
      <div className="field">
        <label htmlFor="role-title" className="lbl">TITLE</label>
        <input id="role-title" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="field">
        <span className="lbl" id="role-model">MODEL</span>
        <div className="segmented" role="radiogroup" aria-labelledby="role-model">
          {choices.map((m) => (
            <button key={m.id} type="button" role="radio" aria-checked={model === m.id} className={model === m.id ? "on" : ""} onClick={() => setModel(m.id)}>
              {m.name}
            </button>
          ))}
        </div>
      </div>
      {isDirector && others.length > 0 && (
        <div className="field">
          <span className="lbl">HIRES</span>
          <div className="toggles">
            {others.map((r) => {
              const on = hires.includes(r.id);
              return (
                <button
                  key={r.id}
                  type="button"
                  aria-pressed={on}
                  className={`toggle${on ? " on" : ""}`}
                  onClick={() => setHires((h) => (on ? h.filter((x) => x !== r.id) : [...h, r.id]))}
                >
                  {r.title || r.id}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div className="field grow">
        <div className="field-head">
          <span className="lbl">PROMPT</span>
          <button type="button" className="link-btn" onClick={() => setEditing((e) => !e)}>
            {editing ? "Preview" : "Edit"}
          </button>
        </div>
        {editing ? (
          <textarea value={prompt} spellCheck onChange={(e) => setPrompt(e.target.value)} aria-label="Prompt" />
        ) : (
          <div className="prompt-read">
            <Markdown text={prompt} />
          </div>
        )}
        {!role.hasAgentFile && <p className="co-quiet">This role has no agent file yet. Saving a prompt creates one.</p>}
      </div>
      <div className="co-actions">
        <button type="button" className="primary" disabled={busy || !dirty || title.trim() === ""} onClick={save}>
          {busy ? "Saving…" : "Save"}
        </button>
        {msg && <span className={msg.ok ? "co-ok" : "co-error"} role="status">{msg.ok ? "✓ Saved" : msg.text}</span>}
      </div>
    </aside>
  );
}
