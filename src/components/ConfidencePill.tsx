import { formatConfidence } from "../lib/format";
import type { CountEvent } from "../types";

// The 0.80 threshold is applied server-side, in Python, not here (docs/api.md
// §6: "the threshold is a rule and belongs where you can see it"). The
// dashboard just trusts needs_review — which also catches cases confidence
// alone wouldn't, like an unapproved device type or a wide/close-up mismatch.
export function ConfidencePill({ event }: { event: CountEvent }) {
  if (event.analyzed_at === null) {
    return <span className="font-mono text-sm text-text-muted">pending</span>;
  }

  const resolved = event.confirmed_at !== null || !event.needs_review;

  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-xs font-medium " +
        (resolved ? "bg-success-soft text-success" : "bg-warning-soft text-warning")
      }
    >
      {resolved ? "✓" : "⚠"} {event.confidence !== null ? formatConfidence(event.confidence) : "—"}
      {!resolved && " review"}
    </span>
  );
}
