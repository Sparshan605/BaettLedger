import { useState } from "react";
import { ConfidencePill } from "../components/ConfidencePill";
import { PhotoLightbox } from "../components/PhotoLightbox";
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
  onOpenPhoto,
}: {
  event: CountEvent;
  onOpenReview: (event: CountEvent) => void;
  onOpenPhoto: (event: CountEvent) => void;
}) {
  // Only an unconfirmed low-confidence/flagged photo opens Screen 3 — that is
  // the one tap that can CHANGE a count (docs/dashboard.md §2). Viewing the
  // photo is separate and always available, on the thumbnail.
  const clickable = event.needs_review && event.confirmed_at === null;
  const isCheck = isCheckZone(event.zone);

  return (
    <li
      onClick={clickable ? () => onOpenReview(event) : undefined}
      className={
        "flex flex-col gap-1 border-l-2 border-transparent px-4 py-3 transition-colors sm:px-5" +
        (clickable ? " cursor-pointer hover:border-warning hover:bg-warning-soft" : "")
      }
    >
      <div className="flex items-center gap-3 sm:gap-4">
        {/* A button, not a bare <img>: this is the only way to actually look at
            the evidence, so it has to be reachable by keyboard too. stopPropagation
            keeps it from also firing the row's review handler on a flagged row. */}
        <button
          onClick={(e) => {
            e.stopPropagation();
            onOpenPhoto(event);
          }}
          aria-label={`View ${event.zone} photo full size`}
          className="group relative shrink-0 rounded-lg focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <img
            src={event.photo_url}
            alt=""
            className="h-14 w-20 rounded-lg border border-border object-cover transition-opacity group-hover:opacity-70"
          />
          <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/40 font-mono text-xs font-semibold text-white opacity-0 transition-opacity group-hover:opacity-100">
            view
          </span>
        </button>

        {/* Wraps rather than squeezing. At 375px the five columns do not fit on
            one line: the clock used to push past the card's right edge and the
            device summary collapsed to zero width, which is what made the whole
            panel look cut off. basis-32 gives the summary a floor, so the
            confidence and clock drop to a second line instead of crushing it. */}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1.5">
          <span
            className={
              "w-16 shrink-0 font-mono text-xs font-semibold uppercase tracking-wider sm:w-20 " +
              (isCheck ? "text-accent" : "text-text-muted")
            }
          >
            {isCheck ? "check" : event.zone}
          </span>

          <span className="min-w-0 flex-1 basis-32 truncate font-medium text-ink">
            {event.analyzed_at === null ? (
              <span className="font-mono font-normal text-text-muted">pending</span>
            ) : (
              summarizeDevices(event.devices)
            )}
          </span>

          <span className="flex shrink-0 justify-end">
            <ConfidencePill event={event} />
          </span>
          <span className="shrink-0 text-right font-mono text-sm tabular-nums text-text-muted sm:w-[4.5rem]">
            {formatClock(event.captured_at)}
          </span>
        </div>
      </div>

      {/* Wherever the reason lands, show it. The cross-check now flags the
          COUNTED row, because that is the one whose correction moves the
          headline total (db.run_zone_overview_cross_check) — gating this on the
          check row would hide the single most useful sentence on the screen at
          exactly the moment something has gone wrong (docs/dashboard.md §2). */}
      {event.reason && (
        <p className="pl-0 font-mono text-xs text-warning sm:pl-[6.5rem]">{event.reason}</p>
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
  const [viewing, setViewing] = useState<CountEvent | null>(null);

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
        <div className="rounded-2xl border border-border bg-surface p-10 text-center text-text-muted">
          Loading…
        </div>
      ) : events.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface p-10 text-center text-text-muted">
          No photos yet.
        </div>
      ) : (
        // The list lives in a card, like the table on Screen 1. Bare rows on the
        // page background left the content looking like an unfinished box with
        // its right edge cut off, especially with only two rows in it.
        <div className="overflow-hidden rounded-2xl border border-border bg-surface">
          <ul className="divide-y divide-border">
            {countedEvents.map((event) => (
              <PhotoRow
                key={event.event_id}
                event={event}
                onOpenReview={onOpenReview}
                onOpenPhoto={setViewing}
              />
            ))}
          </ul>
          {checkEvent && (
            <ul className="border-t-2 border-dashed border-border">
              <PhotoRow
                event={checkEvent}
                onOpenReview={onOpenReview}
                onOpenPhoto={setViewing}
              />
            </ul>
          )}
        </div>
      )}

      {viewing && <PhotoLightbox event={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}
