import { useState } from "react";
import { confirmEvent } from "../api/client";
import { formatConfidence } from "../lib/format";
import { DEVICE_TYPES, type CountEvent, type DeviceType } from "../types";

interface ReviewModalProps {
  event: CountEvent;
  onCancel: () => void;
  onConfirmed: (event: CountEvent) => void;
}

// Screen 3. Opened by tapping an amber row on the Events screen. The whole
// interaction is meant to be one tap: fix the number, hit Confirm
// (docs/dashboard.md §2) — so this stays a single form, no extra steps.
export function ReviewModal({ event, onCancel, onConfirmed }: ReviewModalProps) {
  const [deviceType, setDeviceType] = useState<DeviceType>(event.device_type ?? "unknown");
  const [count, setCount] = useState(event.count ?? 1);
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirm() {
    setSubmitting(true);
    try {
      const result = await confirmEvent(event.event_id, { device_type: deviceType, count });
      onConfirmed({
        ...event,
        device_type: deviceType,
        count,
        confirmed_at: result.confirmed_at,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="animate-modal-in w-full max-w-md rounded-2xl border border-border bg-surface p-6">
        <img
          src={event.photo_url}
          alt="Captured device"
          className="mb-4 w-full rounded-xl border border-border object-cover"
        />

        <p className="text-sm text-text">
          The agent saw:{" "}
          <span className="font-mono font-medium text-ink">
            {event.count ?? "?"} {event.device_type ?? "unknown"}
          </span>{" "}
          <span className="font-mono text-text-muted">
            · confidence {event.confidence !== null ? formatConfidence(event.confidence) : "—"}
          </span>
        </p>
        {event.reason && <p className="mt-1 text-sm text-text-muted">Reason: {event.reason}</p>}

        <div className="mt-5 flex gap-4">
          <label className="flex-1 text-xs font-medium uppercase tracking-wider text-text-muted">
            Device type
            <select
              value={deviceType}
              onChange={(e) => setDeviceType(e.target.value as DeviceType)}
              className="mt-1.5 h-11 w-full rounded-xl border border-border bg-surface-raised px-3 font-display text-sm normal-case tracking-normal text-ink focus-visible:outline-2 focus-visible:outline-accent"
            >
              {DEVICE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
          <label className="w-24 text-xs font-medium uppercase tracking-wider text-text-muted">
            Count
            <input
              type="number"
              min={0}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="mt-1.5 h-11 w-full rounded-xl border border-border bg-surface-raised px-3 font-mono text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent"
            />
          </label>
        </div>

        <div className="mt-6 flex gap-3">
          <button
            onClick={onCancel}
            disabled={submitting}
            className="h-11 flex-1 rounded-xl border border-border bg-surface-raised font-medium text-text transition-colors hover:bg-border"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={submitting}
            className="h-11 flex-1 rounded-xl bg-accent font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
          >
            {submitting ? "Confirming…" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
