import { DeviceOfflineDot } from "../components/DeviceOfflineDot";
import type { SessionRef, TodaySummary } from "../types";

interface TodayScreenProps {
  data: TodaySummary | null;
  loading: boolean;
  reconnecting: boolean;
}

function InventoryTile({
  label,
  value,
  session,
}: {
  label: string;
  value: number;
  session: SessionRef | null;
}) {
  const isOpen = session?.status === "open";

  return (
    <div className="flex-1 rounded-2xl border border-border bg-surface p-6 text-center">
      <div className="font-mono text-xs font-medium uppercase tracking-[0.2em] text-text-muted">
        {label}
      </div>
      {isOpen && value === 0 ? (
        <div className="mt-4 text-base font-medium text-text-muted">
          Session open — waiting for the first photo.
        </div>
      ) : (
        <div className="mt-1 font-mono text-6xl font-semibold tabular-nums text-ink">
          {value}
          {/* Still capturing/analysing — this number is about to change.
              docs/dashboard.md §1 and §8: never show a number that looks final
              when it isn't. */}
          {isOpen && <span className="text-text-muted">…</span>}
        </div>
      )}
    </div>
  );
}

function DifferenceBanner({ difference, provisional }: { difference: number; provisional: boolean }) {
  const suffix = provisional ? "…" : "";
  if (difference > 0) {
    return (
      <div className="rounded-2xl border border-danger/30 bg-danger-soft px-6 py-5 text-center text-2xl font-bold tracking-tight text-danger">
        ⚠ {difference} MISSING{suffix}
      </div>
    );
  }
  if (difference < 0) {
    // Not an error — a device counted twice on the way back in. Call it out
    // plainly rather than rendering a negative number (docs/dashboard.md §5).
    return (
      <div className="rounded-2xl border border-warning/30 bg-warning-soft px-6 py-5 text-center text-2xl font-bold tracking-tight text-warning">
        {Math.abs(difference)} EXTRA RETURNED{suffix}
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-success/30 bg-success-soft px-6 py-5 text-center text-2xl font-bold tracking-tight text-success">
      ALL DEVICES RETURNED{suffix}
    </div>
  );
}

export function TodayScreen({ data, loading, reconnecting }: TodayScreenProps) {
  if (loading && !data) {
    return <div className="p-8 text-center text-text-muted">Loading…</div>;
  }

  if (!data || (!data.out_session && !data.in_session)) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-10 text-center text-lg text-text-muted">
        No count started yet.
      </div>
    );
  }

  const provisional = data.out_session?.status === "open" || data.in_session?.status === "open";

  return (
    <div className="animate-fade-up space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-ink">
          BaettLedger <span className="text-text-muted">— {data.date}</span>
        </h1>
        <div className="flex items-center gap-2">
          {reconnecting && (
            <span className="rounded-full border border-warning/30 bg-warning-soft px-3 py-1 font-mono text-xs font-medium text-warning">
              reconnecting…
            </span>
          )}
          <DeviceOfflineDot deviceLastSeen={data.device_last_seen} />
        </div>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row">
        <InventoryTile
          label="Starting inventory"
          value={data.starting_inventory}
          session={data.out_session}
        />
        <InventoryTile
          label="Ending inventory"
          value={data.ending_inventory}
          session={data.in_session}
        />
      </div>

      <DifferenceBanner difference={data.difference} provisional={provisional} />

      <div className="overflow-hidden rounded-2xl border border-border bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="font-mono text-xs font-medium uppercase tracking-wider text-text-muted">
            <tr>
              <th className="px-4 py-3">Device</th>
              <th className="px-4 py-3">Out</th>
              <th className="px-4 py-3">In</th>
              <th className="px-4 py-3">Missing</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.by_type.map((row) => (
              <tr key={row.device_type}>
                <td className="px-4 py-3 font-medium text-ink">{row.device_type}</td>
                <td className="px-4 py-3 font-mono tabular-nums text-text">{row.out_total}</td>
                <td className="px-4 py-3 font-mono tabular-nums text-text">{row.in_total}</td>
                <td
                  className={
                    "px-4 py-3 font-mono font-semibold tabular-nums " +
                    (row.difference > 0
                      ? "text-danger"
                      : row.difference < 0
                        ? "text-warning"
                        : "text-text-muted")
                  }
                >
                  {row.difference}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.pending_analysis > 0 && (
        <p className="font-mono text-xs text-text-muted">
          {data.pending_analysis} event{data.pending_analysis === 1 ? "" : "s"} still analyzing.
        </p>
      )}
    </div>
  );
}
