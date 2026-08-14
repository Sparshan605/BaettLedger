import type {
  ConfirmPayload,
  ConfirmResponse,
  EventsResponse,
  TodaySummary,
} from "../types";

// Always the real API. There is deliberately no mock fallback.
//
// The dashboard was originally built against static JSON in /mocks so the
// screens could be written before the backend existed. Once deployed, that
// fallback showed fabricated numbers — 15 out, 3 in, 12 missing — under a green
// "live" badge, because VITE_API_BASE was unset at build time and nothing
// distinguished sample data from real data on screen.
//
// A real zero is honest and a fabricated total is not, so the default is now the
// production API rather than mocks. If the backend is down the screens show
// their error and empty states, which is the correct thing to show.
const DEFAULT_API_BASE = "https://func-baettledger.azurewebsites.net";
const API_BASE = (import.meta.env.VITE_API_BASE ?? DEFAULT_API_BASE).replace(/\/+$/, "");

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${url} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export async function getToday(date: string): Promise<TodaySummary> {
  return fetchJson<TodaySummary>(
    `${API_BASE}/api/today?date=${encodeURIComponent(date)}`,
  );
}

export async function getEvents(sessionId: string): Promise<EventsResponse> {
  return fetchJson<EventsResponse>(
    `${API_BASE}/api/events?session_id=${encodeURIComponent(sessionId)}`,
  );
}

export async function getReview(): Promise<EventsResponse> {
  return fetchJson<EventsResponse>(`${API_BASE}/api/review`);
}

export async function confirmEvent(
  eventId: number,
  payload: ConfirmPayload,
): Promise<ConfirmResponse> {
  return fetchJson<ConfirmResponse>(`${API_BASE}/api/events/${eventId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
