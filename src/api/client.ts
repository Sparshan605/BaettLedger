import type {
  ConfirmPayload,
  ConfirmResponse,
  EventsResponse,
  TodaySummary,
} from "../types";

// Per docs/dashboard.md §4: build against static mock JSON first, then swap one
// base URL once the real Function App is live. Empty VITE_API_BASE means "use mocks".
const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const USE_MOCKS = API_BASE === "";
const MOCKS_BASE = "/mocks";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${url} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function getToday(date: string): Promise<TodaySummary> {
  if (USE_MOCKS) {
    return fetchJson<TodaySummary>(`${MOCKS_BASE}/today.json`);
  }
  return fetchJson<TodaySummary>(`${API_BASE}/api/today?date=${encodeURIComponent(date)}`);
}

export async function getEvents(sessionId: string): Promise<EventsResponse> {
  if (USE_MOCKS) {
    // The mock file is one dictionary keyed by session_id so both OUT and IN
    // tabs can be exercised from a single static fixture.
    const all = await fetchJson<Record<string, EventsResponse["events"]>>(
      `${MOCKS_BASE}/events.json`,
    );
    return { events: all[sessionId] ?? [] };
  }
  return fetchJson<EventsResponse>(
    `${API_BASE}/api/events?session_id=${encodeURIComponent(sessionId)}`,
  );
}

export async function getReview(): Promise<EventsResponse> {
  if (USE_MOCKS) {
    return fetchJson<EventsResponse>(`${MOCKS_BASE}/review.json`);
  }
  return fetchJson<EventsResponse>(`${API_BASE}/api/review`);
}

export async function confirmEvent(
  eventId: number,
  payload: ConfirmPayload,
): Promise<ConfirmResponse> {
  if (USE_MOCKS) {
    // No backend to write to in mock mode — simulate the round trip so the UI
    // flow (tap row, correct it, watch it turn green) is fully testable offline.
    await new Promise((resolve) => setTimeout(resolve, 200));
    return { event_id: eventId, confirmed_at: new Date().toISOString() };
  }
  return fetchJson<ConfirmResponse>(`${API_BASE}/api/events/${eventId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
