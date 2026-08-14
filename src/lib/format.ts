// The API stores every timestamp in UTC (docs/api.md §5). We convert to
// Mountain Time only here, at display time, and nowhere else.
const MOUNTAIN_TIME = "America/Denver";

export function formatClock(isoUtc: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: MOUNTAIN_TIME,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(isoUtc));
}

export function formatConfidence(confidence: number): string {
  return confidence.toFixed(2);
}

// True once a timestamp is more than two minutes old — used for the "device
// offline" indicator (docs/dashboard.md §5). The Pi keeps counting locally
// even while offline, so this is informational, not an error state.
export function isStale(isoUtc: string | null, staleAfterMs = 2 * 60 * 1000): boolean {
  if (!isoUtc) return true;
  return Date.now() - new Date(isoUtc).getTime() > staleAfterMs;
}

// "3 cone, 1 sign" for a photo's detections. Only call this for an analysed
// photo — an empty list here means a genuinely empty one ("0"), which is
// distinct from "not analysed yet" (docs/dashboard.md §5).
export function summarizeDevices(devices: { device_type: string; count: number }[]): string {
  if (devices.length === 0) return "0";
  return devices.map((d) => `${d.count} ${d.device_type}`).join(", ");
}
