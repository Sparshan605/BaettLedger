import { useEffect } from "react";
import { createPortal } from "react-dom";
import { formatClock, summarizeDevices } from "../lib/format";
import { isCheckZone, type CountEvent } from "../types";

// Full-size view of one capture. Every photo opens this on tap, whether or not
// it is flagged — the thumbnails are 80px wide and a cone at the back of the bed
// is a few pixels in them, so "is that count right?" is not a question the list
// can answer. Screen 3 (ReviewModal) is still the only place a count can be
// CHANGED; this one is read-only on purpose, so looking at the evidence during a
// demo cannot accidentally edit it.
export function PhotoLightbox({
  event,
  onClose,
}: {
  event: CountEvent;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isCheck = isCheckZone(event.zone);

  // Portalled to <body> deliberately. PhotosScreen's wrapper carries
  // `animate-fade-up`, whose keyframes leave a transform on the element even
  // after the animation settles — and a transformed ancestor becomes the
  // containing block for `position: fixed`. Rendered in place, this overlay
  // sized itself to the photo panel (976x218) instead of the viewport, so the
  // photo it exists to show came out clipped to a sliver.
  return createPortal(
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm"
    >
      <div
        // Clicks inside the panel must not fall through to the backdrop, or
        // trying to look closely at the photo closes it.
        onClick={(e) => e.stopPropagation()}
        className="animate-modal-in flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-border bg-surface"
      >
        <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
          <div className="flex items-baseline gap-3">
            <span
              className={
                "font-mono text-xs font-semibold uppercase tracking-wider " +
                (isCheck ? "text-accent" : "text-text-muted")
              }
            >
              {isCheck ? "check" : event.zone}
            </span>
            <span className="font-medium text-ink">
              {event.analyzed_at === null ? (
                <span className="font-mono font-normal text-text-muted">pending</span>
              ) : (
                summarizeDevices(event.devices)
              )}
            </span>
            <span className="font-mono text-sm tabular-nums text-text-muted">
              {formatClock(event.captured_at)}
            </span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-lg px-2 py-1 font-mono text-sm text-text-muted transition-colors hover:bg-border hover:text-ink"
          >
            esc ✕
          </button>
        </div>

        {isCheck && (
          <p className="border-b border-border px-5 py-2 text-sm text-text-muted">
            A second opinion on the same load — this number is not part of the inventory total.
          </p>
        )}
        {event.reason && (
          <p className="border-b border-border px-5 py-2 font-mono text-xs text-warning">
            {event.reason}
          </p>
        )}

        {/* min-h-0 lets the image shrink inside the flex column instead of
            pushing the header off the top of a short window. */}
        <div className="min-h-0 flex-1 overflow-auto bg-black/30 p-2">
          <img
            src={event.photo_url}
            alt={`${event.zone} capture at ${formatClock(event.captured_at)}`}
            className="mx-auto max-h-[70vh] w-auto max-w-full rounded-lg object-contain"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
