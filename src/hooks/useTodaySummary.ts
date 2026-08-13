import { useEffect, useRef, useState } from "react";
import { getToday } from "../api/client";
import type { TodaySummary } from "../types";

const POLL_MS = 5000;

interface TodayState {
  data: TodaySummary | null;
  loading: boolean;
  // True when the last poll failed but we still have a previous good value.
  // The screen must keep showing that value, never blank on a timeout
  // (docs/dashboard.md §5).
  reconnecting: boolean;
}

// Single poller for /api/today, shared by the Today screen (for the headline
// numbers) and the Events screen (for the OUT/IN session ids). Only one
// interval running matches "poll /api/today every 5 seconds, do not build
// SignalR" from the spec — a second poll loop elsewhere would just be noise.
export function useTodaySummary(date: string): TodayState {
  const [state, setState] = useState<TodayState>({
    data: null,
    loading: true,
    reconnecting: false,
  });
  const lastGood = useRef<TodaySummary | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await getToday(date);
        if (cancelled) return;
        lastGood.current = data;
        setState({ data, loading: false, reconnecting: false });
      } catch {
        if (cancelled) return;
        // Keep the last good numbers on screen; just flag the connection issue.
        setState((prev) => ({
          data: lastGood.current ?? prev.data,
          loading: false,
          reconnecting: true,
        }));
      }
    }

    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [date]);

  return state;
}
