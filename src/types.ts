// Shapes mirror docs/api.md exactly. If the two ever disagree, api.md wins (per docs/dashboard.md).
//
// Rewritten Aug 13: the Pi no longer counts devices one at a time through a beam. It photographs
// the loaded truck bed once and sends two images of that capture, and a single photo can contain
// several device types at once. See docs/api.md §1.

export type SessionType = "OUT" | "IN";
export type SessionStatus = "open" | "closed";

// "wide" is the uncropped frame and is the only thing added to a total. "closeup" is the same
// load through a tighter frame, counted separately purely so two numbers can disagree.
// left/middle/right/overview are the retired three-zone design — sessions captured under it are
// still in the database and still render, so the type has to keep admitting them.
export type CountedZone = "wide" | "left" | "middle" | "right";
export type CheckZone = "closeup" | "overview";
export type Zone = CountedZone | CheckZone;

// The one place that decides whether a photo is arithmetic or evidence. Everything that filters,
// sums, or lays out events must go through this — a second copy of the rule is how the check
// photo ends up inside a total, and it does it plausibly enough that nobody notices.
export const CHECK_ZONES: readonly Zone[] = ["closeup", "overview"];

export function isCheckZone(zone: Zone): boolean {
  return CHECK_ZONES.includes(zone);
}

// The fixed, closed set of device types the Count Agent is allowed to return.
// Never let free text from the API leak past this into a <select>.
export const DEVICE_TYPES = ["cone", "sign", "barricade", "delineator", "barrel", "unknown"] as const;
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
