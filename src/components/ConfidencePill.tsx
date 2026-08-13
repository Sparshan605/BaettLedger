import { formatConfidence } from "../lib/format";
import type { CountEvent } from "../types";

const REVIEW_THRESHOLD = 0.8;

// >= 0.80 (or already confirmed by a human) reads as resolved/green. Below
// that, amber and clickable — tapping it is how Screen 3 opens
// (docs/dashboard.md §2).
export function ConfidencePill({ event }: { event: CountEvent }) {
  if (event.confidence === null) {
    return <span className="font-mono text-sm text-text-muted">pending</span>;
  }

  const resolved = event.confirmed_at !== null || event.confidence >= REVIEW_THRESHOLD;

  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium " +
        (resolved ? "bg-success-soft text-success" : "bg-warning-soft text-warning")
      }
    >
      {resolved ? "✓" : "⚠"} {formatConfidence(event.confidence)}
      {!resolved && " review"}
    </span>
  );
}
