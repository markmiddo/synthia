import { useCallback, useEffect, useState } from "react";
import { useBrain } from "./hud/brain";
import { Connection } from "./hud/Connection";
import { CountsBar } from "./hud/CountsBar";
import { DayPicker } from "./hud/DayPicker";
import { localDate } from "./hud/format";
import { useFleet, useNow, useSynthiaState, useUsage, useVoiceRunning } from "./hud/hooks";
import { NeedsYou } from "./hud/NeedsYou";
import { Orb, orbState } from "./hud/Orb";
import { OrgTree, PastTree } from "./hud/OrgTree";
import { Spoken } from "./hud/Spoken";
import { call } from "./hud/tauri";
import type { DayChart } from "./hud/types";
import "./hud/tokens.css";
import "./hud/hud.css";

function App() {
  const { view, confirmReply } = useBrain();
  const fleet = useFleet();
  const usage = useUsage();
  const voice = useSynthiaState();
  const { running, start } = useVoiceRunning();
  const now = useNow();

  const today = localDate(new Date(now));
  const [day, setDay] = useState(today);
  const [past, setPast] = useState<DayChart | null>(null);
  const viewingToday = day === today;

  useEffect(() => {
    if (viewingToday) return;
    let alive = true;
    setPast(null);
    call<DayChart>("fleet_day", { date: day })
      .then((c) => alive && setPast(c))
      .catch(() => alive && setPast(null));
    return () => {
      alive = false;
    };
  }, [day, viewingToday]);

  const focus = useCallback((paneId: string) => {
    call("fleet_focus", { paneId }).catch((e) => console.warn("could not focus pane", e));
  }, []);

  const nodes = fleet?.nodes ?? [];

  return (
    <main className="hud">
      <aside className="left">
        <Orb state={orbState(voice.recording, view.state)} />
        <Connection brain={view} fleet={fleet} voiceRunning={running} onStartVoice={start} />
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
          <PastTree chart={past} />
        ) : fleet === null ? (
          <p className="empty">Looking for your agents…</p>
        ) : (
          <OrgTree nodes={nodes} now={now} onFocus={focus} />
        )}
        <DayPicker selected={day} onSelect={setDay} />
      </section>
    </main>
  );
}

export default App;
