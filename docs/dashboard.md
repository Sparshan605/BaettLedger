# BaettLedger — Dashboard

**Owner: Shivang** · Three screens on Azure Static Web Apps.
The API you consume is defined in [api.md](api.md) — that document wins if these disagree.

Demo: **August 19, 2026.**

---

## 1. What this shows

One screen answers the whole project:

> **4 went out. 3 came back. 1 cone is missing.**

Everything else supports that sentence. If you are ever unsure whether to build something,
ask whether it makes that line clearer. If not, skip it.

**One user, one role.** No crew/supervisor split, no permission logic. The person running the
truck is the person looking at the screen.

---

## 2. The three screens

### Screen 1 — Today

The landing page. Three numbers, big.

```
              BaettLedger — Aug 19, 2026

    STARTING INVENTORY          ENDING INVENTORY
            4                          3

                  ⚠  1 MISSING

    ┌──────────────┬─────────┬──────────┬───────────┐
    │ Device       │   Out   │    In    │  Missing  │
    ├──────────────┼─────────┼──────────┼───────────┤
    │ cone         │    3    │    2     │     1     │
    │ sign         │    1    │    1     │     0     │
    └──────────────┴─────────┴──────────┴───────────┘
```

- Missing > 0 → red. Zero → green, "All devices returned".
- Both headline numbers are the three zones summed, **overview excluded**.
- If any photo in the session is still pending, mark the total provisional (a trailing "…")
  rather than showing a number that is about to change.
- Poll `/api/today` every 5 seconds. Do not build SignalR.

### Screen 2 — Photos

The four photos behind the numbers. This is where confidence lives.

Each row: thumbnail · zone · what was found · **confidence** · time.

```
  [photo]  LEFT       3 cone, 1 sign    0.94  ✓         08:17:22
  [photo]  MIDDLE     5 cone            0.88  ✓         08:17:48
  [photo]  RIGHT      4 cone            0.91  ✓         08:18:03
  ────────────────────────────────────────────────────────────────
  [photo]  OVERVIEW   7 cone            0.55  ⚠ check   08:18:31
           zones total 12 cones, overview shows 7
```

- Confidence ≥ 0.80 → green check. Below → amber, clickable, opens Screen 3.
- `analyzed_at` still null → show "pending", not an error. Vision runs a few seconds behind.
- **Separate the overview from the three zones**, as above. The zones add up to the total; the
  overview does not participate. Putting it in the same list unseparated invites the reader to
  add all four rows, which is the exact mistake the design is trying to prevent.
- Show the mismatch reason inline under the overview when there is one — that sentence is the
  most useful thing on the screen when something has gone wrong.
- Filter by session (OUT / IN).

### Screen 3 — Review

Opens when a low-confidence event is clicked. This is the 1:30 beat of the demo, so it has
to be one tap.

```
        [ the photo, large ]

   Zone: LEFT                  confidence 0.61
   Reason: devices overlap, could not separate

   cone        [ 3 ]  ⊖
   sign        [ 1 ]  ⊖
   + add type

        [ Confirm ]        [ Cancel ]
```

- One row per device type, each with a number you can edit and a remove button. "+ add type"
  offers the fixed list: **cone, sign, barricade, delineator, unknown**. Never free text.
- Confirm → `POST /api/events/{id}/confirm` with the whole `devices` list, then straight back to
  the list with the row now green.
- Keep it to: tap the amber row, fix the numbers, tap Confirm.

**This screen is now a fallback, not just a nicety.** If Vision is down or over quota on the
day, these photos plus this screen are the only way to produce a count at all — so it has to
work with `devices` empty, letting the operator enter the numbers from scratch.

---

## 3. The API you consume

### `GET /api/today?date=2026-08-19`
```json
{
  "date": "2026-08-19",
  "starting_inventory": 4,
  "ending_inventory": 3,
  "difference": 1,
  "out_session": { "session_id": "sess-2026-08-19-0815", "status": "closed" },
  "in_session":  { "session_id": "sess-2026-08-19-1630", "status": "closed" },
  "by_type": [
    { "device_type": "cone", "out_total": 3, "in_total": 2, "difference": 1 },
    { "device_type": "sign", "out_total": 1, "in_total": 1, "difference": 0 }
  ],
  "device_last_seen": "2026-08-19T16:41:02Z",
  "pending_analysis": 0
}
```

### `GET /api/events?session_id=sess-2026-08-19-0815`

One entry per photo. Four per session: three zones plus the overview. `devices` is a **list**,
because a zone can hold cones and a sign at once.

```json
{ "events": [
  { "event_id": 42, "sequence": 1, "zone": "left",
    "devices": [ { "device_type": "cone", "count": 3 },
                 { "device_type": "sign", "count": 1 } ],
    "confidence": 0.94, "needs_review": false, "reason": null,
    "photo_url": "https://.../photos/....jpg",
    "captured_at": "2026-08-19T08:17:22Z",
    "analyzed_at": "2026-08-19T08:17:29Z", "confirmed_at": null },

  { "event_id": 45, "sequence": 4, "zone": "overview",
    "devices": [ { "device_type": "cone", "count": 7 } ],
    "confidence": 0.55, "needs_review": true,
    "reason": "zones total 12 cones, overview shows 7",
    "photo_url": "https://.../photos/....jpg",
    "captured_at": "2026-08-19T08:18:31Z",
    "analyzed_at": "2026-08-19T08:18:38Z", "confirmed_at": null }
]}
```

`analyzed_at: null` means Vision has not run yet — show "pending", never "0".

**The overview row is evidence, not arithmetic.** Mark it visually as a check rather than a
zone, and never add its counts to anything you display as a total.

### `GET /api/review`
Same shape, only `needs_review = true` and `confirmed_at IS NULL`.

### `POST /api/events/{event_id}/confirm`
```json
{ "devices": [ { "device_type": "cone", "count": 3 },
               { "device_type": "sign", "count": 1 } ] }
```
→ `200 {"event_id": 42, "confirmed_at": "2026-08-19T08:19:10Z"}`

Sending `devices` replaces every detection on that event. To zero a zone, send an empty list.

---

## 4. Build against mocks first

**Do not wait for the API.** Put those four JSON blobs in `/mocks/*.json`, point the app at
them, and build all three screens today. Swap one base URL when the API is live.

```js
const BASE = import.meta.env.VITE_API_BASE ?? '/mocks';
```

Make sure your mock set includes the ugly cases, because those are the ones that break layouts:

- a session with **only two of four photos** taken so far (the operator is mid-sequence)
- an event still `pending` — `analyzed_at: null`, `devices: []`
- a zone with **three device types at once**, which is the row most likely to overflow
- an empty zone — `devices: []` but `analyzed_at` set. Must read "0", not "pending"
- a `device_type` of `unknown`
- a confidence of exactly `0.80` (the boundary — green or amber? pick one and be consistent)
- an overview that **disagrees** with the zones, carrying a `reason` string
- a difference that is **negative** — more came back than went out. Real, not an error: show
  "1 extra returned"

---

## 5. States that are not "everything worked"

The demo will hit at least one of these in front of guests. Each needs to look deliberate.

| State | What to show |
|---|---|
| No sessions today | "No count started yet." Not a spinner, not an error. |
| Session open, 0 events | "Session open — waiting for first device." |
| `analyzed_at` null | "pending" in grey. Never blank, never error, never "0". |
| Analyzed, `devices` empty | "0" — a genuinely empty zone. Different from pending. |
| `/api/today` fails | Keep the last good numbers on screen, add a small amber "reconnecting…". **Never blank the screen.** |
| `device_last_seen` > 2 min old | Small grey "device offline" dot. The Pi is still counting locally and will catch up. |
| Difference is negative | "1 extra returned" — a real state, not an error. |

That fourth row matters most. A screen that goes blank mid-demo reads as total failure, when
usually one poll just timed out.

---

## 6. Stack

**Plain HTML + JS, or Vite + React if you already know it.** Static Web Apps serves either on
the free tier. Do not learn a framework this week. Three screens, four `fetch` calls, one
`setInterval`. Ship it and spend the saved time on the states in §5.

Auth: leave it public for the demo. It is synthetic data (proposal §8), guests may want to
click, and a login screen between an audience and the payoff costs more than it protects.

---

## 7. Build order

| Day | Do this |
|---|---|
| Aug 13 | Static Web App deployed with mocks. A live URL, today. |
| Aug 14 | Screen 1 against mocks |
| Aug 15 | Screens 2 and 3 against mocks |
| Aug 16 | Point at the real API |
| Aug 17 | Every state in §5 |
| Aug 18 | Dry run on a phone and a laptop |

---

## 8. What the demo needs from you

From proposal §14, updated for the zone design — the beats your screens have to carry:

- **0:30** — the OUT inventory. Four photos land over about a minute. Screen 2 fills in a row at
  a time, each going from "pending" to a count. Screen 1's total climbs as the zones resolve.
- **1:30** — a zone with stacked devices comes back low-confidence. The amber row appears, the
  presenter taps it, corrects the numbers on Screen 3, and it turns green — the total on Screen 1
  updating to match is the moment that sells the human check.
- **2:45** — the IN inventory, one cone short. Screen 1 reads **12 out, 11 in, 1 missing**,
  with the eight photos behind it.

Two things to get right for the stage, both about not looking broken:

**Pending must never look like zero.** Between a photo landing and Vision finishing there are a
few seconds where the count is unknown. On a projector, a big "0" reads as failure. Show
"pending", and mark a session total provisional while any of its photos are still unanalysed.

**The overview row must be visibly separate.** A guest who adds all four rows and gets a
different number than the headline will say so out loud.

If those beats work on a phone hotspot, the dashboard is done.
