import { ConfidencePill } from "../components/ConfidencePill";
import { formatClock, summarizeDevices } from "../lib/format";
import { isCheckZone } from "../types";
import type { CountEvent, SessionRef, SessionType } from "../types";

interface PhotosScreenProps {
  tab: SessionType;
  onTabChange: (tab: SessionType) => void;
  activeSession: SessionRef | null;
  events: CountEvent[];
  loading: boolean;
  onOpenReview: (event: CountEvent) => void;
}

function PhotoRow({
  event,
  onOpenReview,
}: {
  event: CountEvent;
  onOpenReview: (event: CountEvent) => void;
}) {
  // Only an unconfirmed low-confidence/flagged photo is clickable — that's
  // the one tap that opens Screen 3 (docs/dashboard.md §2).
  const clickable = event.needs_review && event.confirmed_at === null;
  const isCheck = isCheckZone(event.zone);

  return (
    <li
      onClick={clickable ? () => onOpenReview(event) : undefined}
      className={
        "flex flex-col gap-1 border-l-2 border-transparent py-3 pl-3 pr-1 transition-colors" +
        (clickable ? " cursor-pointer hover:border-warning hover:bg-warning-soft" : "")
      }
    >
      <div className="flex items-center gap-4">
        <img
          src={event.photo_url}
          alt=""
          className="h-12 w-16 shrink-0 rounded-lg border border-border object-cover"
        />
        <span
          className={
            "w-20 font-mono text-xs font-semibold uppercase tracking-wider " +
            (isCheck ? "text-accent" : "text-text-muted")
          }
        >
          {isCheck ? "check" : event.zone}
        </span>
        <span className="flex-1 font-medium text-ink">
          {event.analyzed_at === null ? (
            <span className="font-mono font-normal text-text-muted">pending</span>
          ) : (
            summarizeDevices(event.devices)
          )}
        </span>
        <span className="w-32">
          <ConfidencePill event={event} />
        </span>
        <span className="font-mono text-sm tabular-nums text-text-muted">
          {formatClock(event.captured_at)}
        </span>
      </div>
      {/* Wherever the reason lands, show it. The cross-check now flags the
          COUNTED row, because that is the one whose correction moves the
          headline total (db.run_zone_overview_cross_check) — gating this on the
          check row would hide the single most useful sentence on the screen at
          exactly the moment something has gone wrong (docs/dashboard.md §2). */}
      {event.reason && (
        <p className="pl-20 font-mono text-xs text-warning">{event.reason}</p>
      )}
    </li>
  );
}

export function PhotosScreen({
  tab,
  onTabChange,
  activeSession,
  events,
  loading,
  onOpenReview,
}: PhotosScreenProps) {
  // The wide shot IS the inventory total; the close-up never participates.
  // Keeping it visually separate stops a reader from adding both rows and
  // getting a different number than Screen 1 (docs/dashboard.md §2, §8) —
  // which matters more now that there are only two rows and they are so close
  // together on screen.
  const countedEvents = events.filter((e) => !isCheckZone(e.zone));
  const checkEvent = events.find((e) => isCheckZone(e.zone));

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
          No photos yet.
        </div>
      ) : (
        <div>
          <ul className="divide-y divide-border">
            {countedEvents.map((event) => (
              <PhotoRow key={event.event_id} event={event} onOpenReview={onOpenReview} />
            ))}
          </ul>
          {checkEvent && (
            <ul className="mt-2 border-t-2 border-dashed border-border pt-1">
              <PhotoRow event={checkEvent} onOpenReview={onOpenReview} />
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
