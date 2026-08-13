import { isStale } from "../lib/format";

// Live/offline indicator. Green pulse means the Pi checked in recently;
// grey means it hasn't in over two minutes — not an error, the Pi keeps
// counting locally offline and replays on reconnect (docs/dashboard.md §5).
export function DeviceOfflineDot({ deviceLastSeen }: { deviceLastSeen: string | null }) {
  const stale = isStale(deviceLastSeen);

  return (
    <span
      className={
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs " +
        (stale
          ? "border-border bg-surface text-text-muted"
          : "border-success/30 bg-success-soft text-success")
      }
    >
      <span
        className={
          "h-1.5 w-1.5 rounded-full " +
          (stale ? "bg-text-muted" : "bg-success animate-pulse-soft")
        }
      />
      {stale ? "device offline" : "live"}
    </span>
  );
}
