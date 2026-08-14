import { useState } from "react";
import { ReviewModal } from "./components/ReviewModal";
import { useEvents } from "./hooks/useEvents";
import { useTodaySummary } from "./hooks/useTodaySummary";
import { PhotosScreen } from "./screens/PhotosScreen";
import { TodayScreen } from "./screens/TodayScreen";
import type { CountEvent, SessionType } from "./types";

type Screen = "today" | "photos";

function todayDateString(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("today");
  const [tab, setTab] = useState<SessionType>("OUT");
  const [reviewing, setReviewing] = useState<CountEvent | null>(null);

  // Single source of truth for the day's headline numbers and session ids.
  // One 5-second poll, shared by both screens — see useTodaySummary.
  const today = useTodaySummary(todayDateString());
  const activeSession = tab === "OUT" ? today.data?.out_session ?? null : today.data?.in_session ?? null;
  const { events, setEvents, loading: eventsLoading } = useEvents(activeSession?.session_id ?? null);

  function handleConfirmed(updated: CountEvent) {
    setEvents((prev) => prev.map((e) => (e.event_id === updated.event_id ? updated : e)));
    setReviewing(null);
  }

  return (
    <div className="mx-auto min-h-screen max-w-3xl px-4 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="h-2.5 w-2.5 rounded-full bg-accent" />
          <span className="font-mono text-sm font-semibold uppercase tracking-[0.3em] text-text-muted">
            BaettLedger
          </span>
        </div>
        <nav className="flex gap-6 font-mono text-sm font-medium uppercase tracking-wider">
          <button
            onClick={() => setScreen("today")}
            className={screen === "today" ? "text-ink" : "text-text-muted transition-colors hover:text-text"}
          >
            Today
          </button>
          <button
            onClick={() => setScreen("photos")}
            className={screen === "photos" ? "text-ink" : "text-text-muted transition-colors hover:text-text"}
          >
            Photos
          </button>
        </nav>
      </header>

      {screen === "today" ? (
        <TodayScreen data={today.data} loading={today.loading} reconnecting={today.reconnecting} />
      ) : (
        <PhotosScreen
          tab={tab}
          onTabChange={setTab}
          activeSession={activeSession}
          events={events}
          loading={eventsLoading}
          onOpenReview={setReviewing}
        />
      )}

      {reviewing && (
        <ReviewModal
          event={reviewing}
          onCancel={() => setReviewing(null)}
          onConfirmed={handleConfirmed}
        />
      )}
    </div>
  );
}
