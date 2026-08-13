import { ConfidencePill } from "../components/ConfidencePill";
import { formatClock } from "../lib/format";
import type { CountEvent, SessionRef, SessionType } from "../types";

interface EventsScreenProps {
  tab: SessionType;
  onTabChange: (tab: SessionType) => void;
  activeSession: SessionRef | null;
  events: CountEvent[];
  loading: boolean;
  onOpenReview: (event: CountEvent) => void;
}

export function EventsScreen({
  tab,
  onTabChange,
  activeSession,
  events,
  loading,
  onOpenReview,
}: EventsScreenProps) {
  return (
    <div className="animate-fade-up space-y-5">
      <div className="flex gap-6 border-b border-border font-mono text-sm font-medium uppercase tracking-wider">
        {(["OUT", "IN"] as const).map((type) => (
          <button
            key={type}
            onClick={() => onTabChange(type)}
            className={
              "-mb-px border-b-2 pb-3 transition-colors " +
              (tab === type
                ? "border-accent text-ink"
                : "border-transparent text-text-muted hover:text-text")
            }
          >
            {type}
          </button>
        ))}
      </div>

      {!activeSession ? (
        <div className="rounded-2xl border border-border bg-surface p-10 text-center text-text-muted">
          No {tab.toLowerCase()} session today.
        </div>
      ) : loading ? (
        <div className="p-8 text-center text-text-muted">Loading…</div>
      ) : events.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface p-10 text-center text-text-muted">
          No events yet.
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {events.map((event) => {
            // Only an unconfirmed low-confidence row is clickable — that's
            // the one tap that opens Screen 3 (docs/dashboard.md §2).
            const clickable = event.needs_review && event.confirmed_at === null;
            return (
              <li
                key={event.event_id}
                onClick={clickable ? () => onOpenReview(event) : undefined}
                className={
                  "flex items-center gap-4 border-l-2 border-transparent py-3 pl-3 pr-1 transition-colors" +
                  (clickable ? " cursor-pointer hover:border-warning hover:bg-warning-soft" : "")
                }
              >
                <img
                  src={event.photo_url}
                  alt=""
                  className="h-12 w-16 shrink-0 rounded-lg border border-border object-cover"
                />
                <span className="w-24 font-medium text-ink">
                  {event.device_type ?? <span className="font-mono text-text-muted">pending</span>}
                </span>
                <span className="w-10 font-mono tabular-nums text-text">
                  {event.count !== null ? `×${event.count}` : "—"}
                </span>
                <span className="w-32">
                  <ConfidencePill event={event} />
                </span>
                <span className="ml-auto font-mono text-sm tabular-nums text-text-muted">
                  {formatClock(event.captured_at)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
