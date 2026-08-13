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
- The two headline numbers come from the **event counts**, which are always correct.
  The per-type table comes from Vision and may have gaps — that is fine, show a dash.
- Poll `/api/today` every 5 seconds. Do not build SignalR.

### Screen 2 — Events

The list behind the numbers. This is where confidence lives.

Each row: thumbnail · device type · count · **confidence** · time.

```
  [photo]  cone        ×1     0.94  ✓        08:17:22
  [photo]  cone        ×2     0.61  ⚠ review 08:17:48
  [photo]  sign        ×1     0.88  ✓        08:18:03
  [photo]  —           —      —     pending  08:18:31
```

- Confidence ≥ 0.80 → green check. Below → amber, clickable, opens Screen 3.
- `device_type` still NULL → show "pending", not an error. Vision runs a few seconds behind.
- Filter by session (OUT / IN).

### Screen 3 — Review

Opens when a low-confidence event is clicked. This is the 1:30 beat of the demo, so it has
to be one tap.

```
        [ the photo, large ]

   The agent saw:  2 cones     confidence 0.61
   Reason: devices overlap, could not separate

   Device type:  [cone ▾]     Count: [ 2 ]

        [ Confirm ]        [ Cancel ]
```

- Device dropdown is fixed: **cone, sign, barricade, delineator, unknown**. Never free text.
- Confirm → `POST /api/events/{id}/confirm`, then straight back to the list with the row now green.
- The whole interaction is: tap the amber row, fix the number, tap Confirm. Nothing else.

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
```json
{ "events": [
  { "event_id": 42, "sequence": 1, "device_type": "cone", "count": 1,
    "confidence": 0.94, "needs_review": false, "reason": null,
    "photo_url": "https://.../photos/....jpg",
    "captured_at": "2026-08-19T08:17:22Z", "confirmed_at": null }
]}
```

### `GET /api/review`
Same shape, only `needs_review = true` and `confirmed_at IS NULL`.

### `POST /api/events/{event_id}/confirm`
```json
{ "device_type": "cone", "count": 2 }
```
→ `200 {"event_id": 42, "confirmed_at": "2026-08-19T08:19:10Z"}`

---

## 4. Build against mocks first

**Do not wait for the API.** Put those four JSON blobs in `/mocks/*.json`, point the app at
them, and build all three screens today. Swap one base URL when the API is live.

```js
const BASE = import.meta.env.VITE_API_BASE ?? '/mocks';
```

Make sure your mock set includes the ugly cases, because those are the ones that break layouts:
zero events, an event still `pending`, a `device_type` of `unknown`, a confidence of exactly
`0.80`, and a difference that is **negative** (more came back than went out — it happens when a
device is counted twice, and it must not render as a crash).

---

## 5. States that are not "everything worked"

The demo will hit at least one of these in front of guests. Each needs to look deliberate.

| State | What to show |
|---|---|
| No sessions today | "No count started yet." Not a spinner, not an error. |
| Session open, 0 events | "Session open — waiting for first device." |
| `device_type` NULL | "pending" in grey. Never blank, never error. |
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

From proposal §14, the beats your screens have to carry:

- **0:30** — OUT count runs. The number on Screen 1 climbs live as devices pass.
- **1:30** — two overlapping devices trigger low confidence. The amber row appears on Screen 2,
  you tap it, correct it on Screen 3, it turns green.
- **2:45** — the day closes. Screen 1 reads **4 out, 3 in, 1 missing**, with the photos behind it.

If those three moments work on a phone hotspot, the dashboard is done.
