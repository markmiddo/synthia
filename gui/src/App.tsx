import { useCallback, useEffect, useMemo, useState } from "react";
import { useActivity } from "./hud/activity";
import { useBrain } from "./hud/brain";
import { Connection } from "./hud/Connection";
import { CompanyView } from "./hud/CompanyView";
import { InboxDrawer } from "./hud/Inbox";
import { newItems, useInbox } from "./hud/inbox";
import { Constellation } from "./hud/Constellation";
import { Feed } from "./hud/Feed";
import { isPlainShell, lastSevenDays, localDate } from "./hud/format";
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
import { Spoken } from "./hud/Left";
import { Scorecard } from "./hud/Scorecard";
import { useToday, useTodayChart } from "./hud/today";
import { Orb, orbState } from "./hud/Orb";
import { call, MOCK, reasonOf } from "./hud/tauri";
import { fleetFromDay } from "./hud/replay";
import { TopBar, type View } from "./hud/TopBar";
import type { DayChart, Fleet } from "./hud/types";
import "./hud/tokens.css";
import "./hud/hud.css";

function App() {
  const { view, confirmReply } = useBrain();
  const liveFleet = useFleet();
  const fleet = useMemo(
    () => (liveFleet ? { ...liveFleet, nodes: liveFleet.nodes.filter((n) => !isPlainShell(n)) } : null),
    [liveFleet],
  );
  const usage = useUsage();
  const { state: voice, error: voiceStateError } = useSynthiaState();
  const talkKey = useTalkKey(voice);
  const { running, start, error: voiceError } = useVoiceRunning();
  const now = useNow();
  const activity = useActivity(fleet);

  const today = localDate(new Date(now));
  const todayData = useToday();
  const todayChart = useTodayChart(fleet, today);
  const [day, setDay] = useState(today);
  const [past, setPast] = useState<{ status: "loading" } | { status: "error"; reason: string } | { status: "ready"; fleet: Fleet }>({ status: "loading" });
  const [screen, setScreen] = useState<View>(() => {
    try {
      return localStorage.getItem("synthia.hud.view") === "company" ? "company" : "constellation";
    } catch {
      return "constellation";
    }
  });
  const pickView = useCallback((v: View) => {
    setScreen(v);
    try {
      localStorage.setItem("synthia.hud.view", v);
    } catch {
      /* the choice just will not be remembered */
    }
  }, []);
  const [jobRequest, setJobRequest] = useState<{ squad: string; job: string; n: number } | null>(null);
  const openJob = useCallback(
    (squad: string, job: string) => {
      setJobRequest((r) => ({ squad, job, n: (r?.n ?? 0) + 1 }));
      pickView("company");
    },
    [pickView],
  );
  const { items: inboxItems, reload: reloadInbox } = useInbox(view.inboxTick);
  const [inboxOpen, setInboxOpen] = useState<{ id: string | null } | null>(null);
  const openInbox = useCallback((id?: string) => setInboxOpen({ id: id ?? null }), []);
  const closeInbox = useCallback(() => setInboxOpen(null), []);
  const [focusError, setFocusError] = useState<string | null>(null);
  const viewingToday = day === today;

  // A past day is read once from the day record; today is the live fleet.
  useEffect(() => {
    if (viewingToday) return;
    let alive = true;
    setPast({ status: "loading" });
    call<DayChart>("fleet_day", { date: day })
      .then((c) => {
        if (!alive) return;
        const f = fleetFromDay(c);
        setPast({ status: "ready", fleet: { ...f, nodes: f.nodes.filter((n) => !isPlainShell(n)) } });
      })
      .catch((e) => alive && setPast({ status: "error", reason: reasonOf(e) }));
    return () => {
      alive = false;
    };
  }, [day, viewingToday]);

  const pickDay = useCallback((d: string) => {
    setDay(d);
    if (d !== today) setScreen("constellation");
  }, [today]);
  const dayLabel = lastSevenDays(new Date(now)).find((d) => d.date === day)?.label ?? day;

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
      <TopBar nodes={nodes} usage={usage} now={now} preview={MOCK} view={screen} onView={(v) => {
          setDay(today);
          pickView(v);
        }} day={day} today={today} onDay={pickDay} inboxNew={newItems(inboxItems).length} onInbox={() => openInbox()} />
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
        <Scorecard
          today={todayData}
          todayDate={today}
          nodes={nodes}
          chart={todayChart}
          fleet={fleet}
          confirms={view.confirms}
          now={now}
          onFocus={focus}
          onConfirm={confirmReply}
          reviews={newItems(inboxItems).map((i) => ({ id: i.id, title: i.title }))}
          onReview={openInbox}
        />
      </aside>
      {!viewingToday && (
        <p className="replay-banner" role="status">
          <span>
            Viewing {dayLabel}
            {past.status === "loading" ? " · loading…" : past.status === "error" ? ` · I can't read that day: ${past.reason}` : ""}
          </span>
          <button type="button" onClick={() => setDay(today)}>Back to live</button>
        </p>
      )}
      {screen === "company" && viewingToday ? (
        <CompanyView fleet={fleet} now={now} onFocus={focus} request={jobRequest} brain={view} inbox={inboxItems} onOpenInbox={openInbox} />
      ) : (
        <Constellation
          fleet={viewingToday ? fleet : past.status === "ready" ? past.fleet : null}
          now={now}
          onFocus={focus}
          onOpenJob={openJob}
          replay={!viewingToday}
        />
      )}
      <Feed items={activity} />
      {inboxOpen && <InboxDrawer items={inboxItems} initialId={inboxOpen.id} onClose={closeInbox} reload={reloadInbox} fleet={fleet} onOpenJob={openJob} />}
    </main>
  );
}

export default App;
