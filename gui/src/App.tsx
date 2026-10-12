import { useCallback, useEffect, useState } from "react";
import { useActivity } from "./hud/activity";
import { useBrain } from "./hud/brain";
import { Connection } from "./hud/Connection";
import { Constellation } from "./hud/Constellation";
import { DayPicker } from "./hud/DayPicker";
import { Feed } from "./hud/Feed";
import { localDate } from "./hud/format";
import {
  murmurKeyMissing,
  NO_MURMUR_KEY_LINE,
  useFleet,
  useNow,
  useSynthiaState,
  useTalkKey,
  useUsage,
  useVoiceRunning,
} from "./hud/hooks";
import { NeedsYou, Spoken } from "./hud/Left";
import { Orb, orbState } from "./hud/Orb";
import { call, MOCK, reasonOf } from "./hud/tauri";
import { Timeline, type DayState } from "./hud/Timeline";
import { TopBar } from "./hud/TopBar";
import type { DayChart } from "./hud/types";
import "./hud/tokens.css";
import "./hud/hud.css";

function App() {
  const { view, confirmReply } = useBrain();
  const fleet = useFleet();
  const usage = useUsage();
  const { state: voice, error: voiceStateError } = useSynthiaState();
  const talkKey = useTalkKey(voice);
  const { running, start, error: voiceError } = useVoiceRunning();
  const now = useNow();
  const activity = useActivity(fleet);

  const today = localDate(new Date(now));
  const [day, setDay] = useState(today);
  const [chart, setChart] = useState<DayState>({ status: "loading" });
  const [focusError, setFocusError] = useState<string | null>(null);
  const viewingToday = day === today;

  // Today's lanes follow the fleet: reload when something changes, and every minute.
  const fleetKey = fleet ? fleet.nodes.map((n) => `${n.paneId}:${n.status}:${n.subagents.length}`).join("|") : "";
  const minute = Math.floor(now / 60_000);
  useEffect(() => {
    let alive = true;
    call<DayChart>("fleet_day", { date: day })
      .then((c) => alive && setChart({ status: "ready", chart: c }))
      .catch((e) => alive && setChart({ status: "error", reason: reasonOf(e) }));
    return () => {
      alive = false;
    };
  }, [day, viewingToday ? fleetKey : "", viewingToday ? minute : 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (d: string) => {
    setChart({ status: "loading" });
    setDay(d);
  };

  const focus = useCallback((paneId: string) => {
    call("fleet_focus", { paneId })
      .then(() => setFocusError(null))
      .catch((e) => setFocusError(`I couldn't switch to that pane: ${reasonOf(e)}`));
  }, []);

  const nodes = fleet?.nodes ?? [];

  return (
    <main className="hud">
      <div className="sweep" aria-hidden="true" />
      <span className="bracket tl" />
      <span className="bracket tr" />
      <span className="bracket bl" />
      <span className="bracket br" />
      <TopBar nodes={nodes} usage={usage} now={now} preview={MOCK} />
      <aside className="left">
        <Orb state={orbState(voice.recording, view.state)} talkKey={talkKey} />
        <Connection
          brain={view}
          fleet={fleet}
          voiceRunning={running}
          onStartVoice={start}
          talkKey={talkKey}
          notes={[
            ...(focusError ? [focusError] : []),
            ...(voiceError ? [voiceError] : []),
            ...(murmurKeyMissing(voice) ? [NO_MURMUR_KEY_LINE] : []),
            ...(voiceStateError ? [`I can't read the voice state: ${voiceStateError}`] : []),
          ]}
        />
        <Spoken spoken={view.spoken} />
        <NeedsYou nodes={nodes} confirms={view.confirms} now={now} onFocus={focus} onConfirm={confirmReply} />
      </aside>
      <Constellation fleet={fleet} now={now} onFocus={focus} />
      <Feed items={activity} />
      <section className="day" aria-label="Timeline">
        <div className="day-head">
          <p className="lbl">{viewingToday ? "TODAY" : "THAT DAY"}</p>
          <DayPicker selected={day} onSelect={pick} />
        </div>
        <Timeline day={chart} now={now} today={viewingToday} />
      </section>
    </main>
  );
}

export default App;
