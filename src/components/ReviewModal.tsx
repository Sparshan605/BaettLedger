import { useState } from "react";
import { confirmEvent } from "../api/client";
import { formatConfidence } from "../lib/format";
import {
  DEVICE_TYPES,
  isCheckZone,
  type CountEvent,
  type DeviceDetection,
  type DeviceType,
} from "../types";

interface ReviewModalProps {
  event: CountEvent;
  onCancel: () => void;
  onConfirmed: (event: CountEvent) => void;
}

// Screen 3. Opened by tapping a flagged photo. One row per device type, each
// editable and removable, plus "+ add type" from the fixed list — never free
// text (docs/dashboard.md §2). This screen is also the fallback when Vision
// is down entirely, so it has to work starting from an empty devices list,
// not just correct an existing one (docs/dashboard.md §2, "not just a nicety").
export function ReviewModal({ event, onCancel, onConfirmed }: ReviewModalProps) {
  const [devices, setDevices] = useState<DeviceDetection[]>(event.devices);
  const [submitting, setSubmitting] = useState(false);

  const usedTypes = new Set(devices.map((d) => d.device_type));
  const availableTypes = DEVICE_TYPES.filter((t) => !usedTypes.has(t));

  function updateCount(deviceType: DeviceType, count: number) {
    setDevices((prev) => prev.map((d) => (d.device_type === deviceType ? { ...d, count } : d)));
  }

  function removeRow(deviceType: DeviceType) {
    setDevices((prev) => prev.filter((d) => d.device_type !== deviceType));
  }

  function addRow(deviceType: DeviceType) {
    setDevices((prev) => [...prev, { device_type: deviceType, count: 1 }]);
  }

  async function handleConfirm() {
    setSubmitting(true);
    try {
      const result = await confirmEvent(event.event_id, { devices });
      onConfirmed({ ...event, devices, analyzed_at: event.analyzed_at ?? result.confirmed_at, confirmed_at: result.confirmed_at });
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

        <p className="font-mono text-xs font-semibold uppercase tracking-wider text-accent">
          {event.zone} — {isCheckZone(event.zone) ? "cross-check" : "counted"}
        </p>
        {/* Correcting a cross-check photo does NOT move the headline number, and
            nothing else on this screen says so. Someone fixing it on stage and
            watching the total sit still would reasonably conclude the whole
            confirm flow is broken. */}
        {isCheckZone(event.zone) && (
          <p className="mt-1 text-sm text-warning">
            This photo is a second opinion, not the count. Correcting it will not change the
            inventory total.
          </p>
        )}
        <p className="mt-1 text-sm text-text">
          {event.confidence !== null ? (
            <span className="font-mono text-text-muted">
              confidence {formatConfidence(event.confidence)}
            </span>
          ) : (
            <span className="font-mono text-text-muted">not analyzed</span>
          )}
        </p>
        {event.reason && <p className="mt-1 text-sm text-text-muted">Reason: {event.reason}</p>}

        <div className="mt-5 space-y-2">
          {devices.length === 0 && (
            <p className="text-sm text-text-muted">
              No devices recorded yet. Add each type you can see in the photo.
            </p>
          )}
          {devices.map((d) => (
            <div key={d.device_type} className="flex items-center gap-3">
              <span className="flex-1 font-medium capitalize text-ink">{d.device_type}</span>
              <input
                type="number"
                min={0}
                value={d.count}
                onChange={(e) => updateCount(d.device_type, Number(e.target.value))}
                className="h-10 w-20 rounded-xl border border-border bg-surface-raised px-3 font-mono text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent"
              />
              <button
                onClick={() => removeRow(d.device_type)}
                aria-label={`Remove ${d.device_type}`}
                className="flex h-10 w-10 items-center justify-center rounded-xl border border-border bg-surface-raised text-lg text-text-muted transition-colors hover:bg-border hover:text-danger"
              >
                ⊖
              </button>
            </div>
          ))}

          {availableTypes.length > 0 && (
            <select
              value=""
              onChange={(e) => addRow(e.target.value as DeviceType)}
              className="h-10 w-full rounded-xl border border-dashed border-border bg-transparent px-3 text-sm text-text-muted focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="" disabled>
                + add type
              </option>
              {availableTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          )}
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
