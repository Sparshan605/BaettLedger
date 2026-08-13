// Shapes mirror docs/api.md exactly. If the two ever disagree, api.md wins (per docs/dashboard.md).

export type SessionType = "OUT" | "IN";
export type SessionStatus = "open" | "closed";

// The fixed, closed set of device types the Count Agent is allowed to return.
// Never let free text from the API leak past this into a <select>.
export const DEVICE_TYPES = ["cone", "sign", "barricade", "delineator", "unknown"] as const;
export type DeviceType = (typeof DEVICE_TYPES)[number];

export interface SessionRef {
  session_id: string;
  status: SessionStatus;
}

export interface ByTypeTotal {
  device_type: string;
  out_total: number;
  in_total: number;
  difference: number;
}

export interface TodaySummary {
  date: string;
  starting_inventory: number;
  ending_inventory: number;
  difference: number;
  out_session: SessionRef | null;
  in_session: SessionRef | null;
  by_type: ByTypeTotal[];
  device_last_seen: string | null;
  pending_analysis: number;
}

export interface CountEvent {
  event_id: number;
  sequence: number;
  // NULL until Vision + the Count Agent finish analyzing the photo.
  device_type: DeviceType | null;
  count: number | null;
  confidence: number | null;
  needs_review: boolean;
  reason: string | null;
  photo_url: string;
  captured_at: string; // ISO 8601, UTC
  confirmed_at: string | null;
}

export interface EventsResponse {
  events: CountEvent[];
}

export interface ConfirmPayload {
  device_type: DeviceType;
  count: number;
}

export interface ConfirmResponse {
  event_id: number;
  confirmed_at: string;
}
