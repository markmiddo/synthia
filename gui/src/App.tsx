import { useCallback, useEffect, useState } from "react";
import { useBrain } from "./hud/brain";
import { Connection } from "./hud/Connection";
import { CountsBar } from "./hud/CountsBar";
import { DayPicker } from "./hud/DayPicker";
import { localDate } from "./hud/format";
import { useFleet, useNow, useSynthiaState, useUsage, useVoiceRunning } from "./hud/hooks";
import { NeedsYou } from "./hud/NeedsYou";
import { Orb, orbState } from "./hud/Orb";
import { OrgTree, PastTree, type PastDay } from "./hud/OrgTree";
import { Spoken } from "./hud/Spoken";
import { call, reasonOf } from "./hud/tauri";
import type { DayChart } from "./hud/types";
import "./hud/tokens.css";
import "./hud/hud.css";

function App() {
  const { view, confirmReply } = useBrain();
  const fleet = useFleet();
  const usage = useUsage();
  const { state: voice, error: voiceStateError } = useSynthiaState();
  const { running, start, error: voiceError } = useVoiceRunning();
  const now = useNow();

  const today = localDate(new Date(now));
  const [day, setDay] = useState(today);
  const [past, setPast] = useState<PastDay>({ status: "loading" });
  const [focusError, setFocusError] = useState<string | null>(null);
  const viewingToday = day === today;

  useEffect(() => {
    if (viewingToday) return;
    let alive = true;
    setPast({ status: "loading" });
    call<DayChart>("fleet_day", { date: day })
      .then((chart) => alive && setPast({ status: "ready", chart }))
      .catch((e) => alive && setPast({ status: "error", reason: reasonOf(e) }));
    return () => {
      alive = false;
    };
  }, [day, viewingToday]);

  const focus = useCallback((paneId: string) => {
    call("fleet_focus", { paneId })
      .then(() => setFocusError(null))
      .catch((e) => setFocusError(`I couldn't switch to that pane: ${reasonOf(e)}`));
  }, []);

  const nodes = fleet?.nodes ?? [];

  return (
    <main className="hud">
      <aside className="left">
        <Orb state={orbState(voice.recording, view.state)} />
        <Connection
          brain={view}
          fleet={fleet}
          voiceRunning={running}
          onStartVoice={start}
          notes={[
            ...(focusError ? [focusError] : []),
            ...(voiceError ? [voiceError] : []),
            ...(voiceStateError ? [`I can't read the voice state: ${voiceStateError}`] : []),
          ]}
        />
        <Spoken spoken={view.spoken} link={view.link} />
        <NeedsYou
          nodes={nodes}
          confirms={view.confirms}
          now={now}
          onFocus={focus}
          onConfirm={confirmReply}
        />
      </aside>
      <section className="right">
        <CountsBar nodes={nodes} usage={usage} />
        {!viewingToday ? (
          <PastTree day={past} />
        ) : fleet === null ? (
          <p className="empty">Looking for your agents…</p>
        ) : (
          <OrgTree
            nodes={nodes}
            now={now}
            onFocus={focus}
            herdrDown={fleet.herdrOk ? undefined : { error: fleet.error }}
          />
        )}
        <DayPicker selected={day} onSelect={setDay} />
      </section>
    </main>
  );
}

export default App;
