// Shapes mirror docs/api.md exactly. If the two ever disagree, api.md wins (per docs/dashboard.md).
//
// Rewritten Aug 13: the Pi no longer counts devices one at a time through a beam. It photographs
// the truck bed in three fixed zones (left/middle/right) plus one overview shot, and a single
// photo can contain several device types at once. See docs/api.md §1.

export type SessionType = "OUT" | "IN";
export type SessionStatus = "open" | "closed";
export type Zone = "left" | "middle" | "right" | "overview";

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

// What was found in one photo. A single zone can hold several types at once
// (three cones and a sign), so this is a list, not one type/count pair.
export interface DeviceDetection {
  device_type: DeviceType;
  count: number;
}

export interface CountEvent {
  event_id: number;
  sequence: number;
  zone: Zone;
  // Populated once Vision + the Count Agent have run. An empty array after
  // analysis means a genuinely empty zone ("0"), which is different from not
  // having been analysed yet at all (see analyzed_at).
  devices: DeviceDetection[];
  confidence: number | null;
  needs_review: boolean;
  reason: string | null;
  photo_url: string;
  captured_at: string; // ISO 8601, UTC
  // NULL until Vision has run. This — not an empty `devices` list — is what
  // distinguishes "pending" from "analyzed, found nothing" (docs/api.md §1).
  analyzed_at: string | null;
  confirmed_at: string | null;
}

export interface EventsResponse {
  events: CountEvent[];
}

export interface ConfirmPayload {
  // Sending this list replaces every detection on the event. Send an empty
  // list to zero out a zone (docs/dashboard.md §3).
  devices: DeviceDetection[];
}

export interface ConfirmResponse {
  event_id: number;
  confirmed_at: string;
}
