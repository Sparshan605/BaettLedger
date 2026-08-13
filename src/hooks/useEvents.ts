import { useEffect, useState } from "react";
import { getEvents } from "../api/client";
import type { CountEvent } from "../types";

interface EventsState {
  events: CountEvent[];
  setEvents: React.Dispatch<React.SetStateAction<CountEvent[]>>;
  loading: boolean;
}

// Owns the event list for one session. Exposed as state (not re-fetched on
// every render) so a confirmation from Screen 3 can patch a single row in
// place — refetching would just re-read the same mock data and undo it.
export function useEvents(sessionId: string | null): EventsState {
  const [events, setEvents] = useState<CountEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!sessionId) {
      setEvents([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getEvents(sessionId)
      .then((res) => {
        if (!cancelled) setEvents(res.events);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  return { events, setEvents, loading };
}
