# BaettLedger — API

**Owner: Shivang** · You write all the code between the Pi and the dashboard.
Protsahan gives you the resources ([azure-setup.md](azure-setup.md)). Sparshan's Pi calls you.

Demo: **August 19, 2026.**

---

## 0. Ship this today

Sparshan cannot write or test the Pi's uploader until an endpoint exists. Deploy this first,
before you read the rest of this document. It took longer to explain than it will to write.

```python
import azure.functions as func
import logging, os

app = func.FunctionApp()

@app.route(route="health", auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse('{"status":"ok"}', mimetype="application/json")

@app.route(route="events", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def events(req: func.HttpRequest) -> func.HttpResponse:
    if req.headers.get("x-device-key") != os.environ["DEVICE_KEY"]:
        return func.HttpResponse('{"error":"bad key"}', status_code=401, mimetype="application/json")
    logging.info("EVENT: %s", req.form.get("metadata") or req.get_body()[:500])
    return func.HttpResponse('{"status":"accepted"}', status_code=200, mimetype="application/json")
```

Tell Sparshan the moment it is live. He is blocked until then.

---

## 1. What changed, and the rule that replaces the old one

> **This section was rewritten on Aug 13.** The design changed and the old guarantee is gone.
> Read it even if you read this document before.

**Old design:** devices passed an ultrasonic beam one at a time. One crossing = one photo = one
device. The Pi *knew* the count and Vision only labelled it, so a total Vision outage still left
a correct number on the dashboard.

**New design:** the Pi photographs the loaded truck bed **once** and sends two images of that one
capture: **`wide`**, the uncropped frame, and **`closeup`**, the same load with the outer margin
trimmed off. The count comes out of the photos. The Pi no longer knows how many cones there are.

> **Changed Aug 13 (second revision).** This replaced a three-zone split — `left`, `middle`,
> `right` summed together, plus an `overview` cross-check. Thirds tiled the frame exactly, so the
> sum was valid by construction, but a device straddling a boundary got sliced in half in two
> crops and every press put four photos through Vision. Two photos halve the wait and never cut a
> device in half. **The old zone names are still accepted and still total correctly** — sessions
> captured before the change are in the database and must keep rendering.

**So the old rule — "a Vision failure cannot change the count" — is no longer true, and nothing
you write can make it true again.** Do not design as if it still holds.

### The rule that replaces it

**A failure may cost us the number, but it must never cost us the evidence, and it must never
produce a number quietly.**

Three things follow, and all three are your responsibility:

1. **Write the photo and the row before analysing anything.** If Vision dies, the inventory is
   still recoverable by a human looking at the photos. Evidence first, always.
2. **An unanalysed inventory shows as pending or needs-review — never as a total.** A session
   with a failed Vision call must not render as "0 cones". Zero and unknown are different, and
   confusing them in front of guests is worse than showing nothing.
3. **Cross-check the wide shot against the close-up** (§6a). Two independent estimates that
   disagree means something is wrong, and a human should look.

---

## 2. How one truckload becomes a number

1. The operator presses the button **once**, aiming at the whole load. The Pi takes one photo,
   derives the close-up crop from it, and queues both locally.
2. The Pi `POST`s each photo + metadata to `/api/events`, tagged with its `zone` — `wide` first,
   then `closeup`.
3. You check the device key, write the JPEG to Blob, and **insert the `count_event` row
   immediately**, with `analyzed_at = NULL` and no detections yet. Return `201`.
4. You send the photo to Azure AI Vision → objects and tags.
5. You send those to the Count Agent → `{device_type, count, confidence, needs_review, reason}`.
   Unlike the old design, `count` here is usually more than 1 — it is how many devices are in
   that photo.
6. You update the row. If `confidence < 0.80`, set `needs_review = 1`.
7. When both captures for a session have been analysed, compare the two (§6a) and flag the
   session if they disagree.
8. The dashboard reads it.

**The inventory total is `SUM(count)` over the counted photo only** — `wide`, or `left`+`middle`+
`right` for a legacy session. The cross-check photo (`closeup`, or `overview`) is never added: it
covers the same devices, so including it would roughly double every number.

---

## 3. Endpoints

### From the Pi (Sparshan)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Pi shows ONLINE/OFFLINE on the LCD based on this |
| `POST` | `/api/sessions` | Open a session |
| `POST` | `/api/events` | One count event + photo |
| `POST` | `/api/sessions/{session_id}/close` | Close a session |

All Pi requests send `x-device-key: <DEVICE_KEY>`. Missing or wrong → `401`.

#### `POST /api/sessions`
```json
{ "device_id": "baettledger-01", "session_id": "sess-2026-08-19-0815",
  "session_type": "OUT", "opened_at": "2026-08-19T08:15:00Z" }
```
→ `201 {"session_id": "...", "status": "open"}` · already exists → `200`, same body.

#### `POST /api/events`
`multipart/form-data`, two parts:
- `metadata` — JSON
- `photo` — the JPEG

```json
{ "device_id": "baettledger-01", "session_id": "sess-2026-08-19-081500",
  "sequence": 1, "zone": "wide", "captured_at": "2026-08-19T08:17:22Z" }
```
→ `201 {"event_id": 42, "status": "accepted"}`

`zone` is `wide` or `closeup` — or one of the retired `left`, `middle`, `right`, `overview`,
which stay accepted so an un-updated Pi is not rejected mid-demo. **Reject anything else with
`400`** — a typo'd zone would silently drop out of the sum and undercount the whole inventory.

`sequence` is the capture index within the session, 1–2. It still forms the idempotency key
with `device_id` and `session_id` (§4); nothing about duplicate handling changes.

> `session_id` carries **seconds**, not just `HH:MM`. It used to stop at the minute, and two
> presses inside one minute then collided on the same id — the second inventory was silently
> appended to the first session, direction and all, so an OUT capture was filed as sequences
> 5–8 of the preceding IN. Do not assume one session means one capture; assume the id is opaque.

#### `POST /api/sessions/{session_id}/close`
```json
{ "closed_at": "2026-08-19T08:40:00Z" }
```
→ `200 {"session_id":"...", "status":"closed", "total_events": 4}`

### Photos go in the POST — not a SAS token

One request carries the metadata and the JPEG together. It is atomic: you can never end up
with a photo and no row, or a row and no photo. A SAS flow needs two round trips, a third
endpoint, and orphan cleanup on both sides — on a phone hotspot that is a bad trade for a
one-day demo. JPEGs are ~500 KB after the Pi downscales; well under any limit.

### For the dashboard

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/today` | Starting inventory, ending inventory, difference |
| `GET` | `/api/events?session_id=` | Event list with photos and confidence |
| `GET` | `/api/review` | Events needing confirmation |
| `POST` | `/api/events/{id}/confirm` | Human corrects a count |

Shapes are in [dashboard.md](dashboard.md) §3. **If the two documents ever disagree, this one wins.**

---

## 4. Duplicates — read this twice

The Pi is offline-first. It queues events and replays them on reconnect, and it does **not**
know whether a request that timed out actually landed. **It will resend events you already have.**
This is correct behaviour, not a bug, and your job is to absorb it.

An event is uniquely `(device_id, session_id, sequence)`. Enforce it **in the database**, not in
Python — replayed batches hit concurrent function instances and an application-level check loses
that race.

```sql
CONSTRAINT uq_event UNIQUE (device_id, session_id, sequence)
```

On insert, catch the duplicate-key error and return `200` with the existing `event_id`.
Never `409` — Sparshan's uploader treats non-2xx as "retry later", so a `409` would make the
event replay forever.

| Case | Response |
|---|---|
| New event | `201` + new `event_id` |
| Same `(device, session, sequence)` again | `200` + existing `event_id`, **no second row, no second photo, no second Vision call** |
| Same key, different photo | Keep the first. Ignore the new photo. |

---

## 5. Database

Three tables, from proposal §8.

```sql
CREATE TABLE session (
    session_id     NVARCHAR(64)  PRIMARY KEY,
    device_id      NVARCHAR(64)  NOT NULL,
    session_type   NVARCHAR(3)   NOT NULL CHECK (session_type IN ('OUT','IN')),
    session_date   DATE          NOT NULL,
    opened_at      DATETIME2     NOT NULL,
    closed_at      DATETIME2     NULL,
    status         NVARCHAR(10)  NOT NULL DEFAULT 'open'
);

CREATE TABLE count_event (
    event_id     INT IDENTITY(1,1) PRIMARY KEY,
    session_id   NVARCHAR(64) NOT NULL REFERENCES session(session_id),
    device_id    NVARCHAR(64) NOT NULL,
    sequence     INT          NOT NULL,
    zone         NVARCHAR(10) NOT NULL
        CONSTRAINT ck_event_zone CHECK
            (zone IN ('wide','closeup','left','middle','right','overview')),
    captured_at  DATETIME2    NOT NULL,   -- Pi clock
    received_at  DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),  -- server clock, trust this one
    photo_url    NVARCHAR(400) NULL,
    analyzed_at  DATETIME2     NULL,      -- NULL until Vision has run
    confidence   DECIMAL(4,3)  NULL,
    needs_review BIT           NOT NULL DEFAULT 0,
    reason       NVARCHAR(400) NULL,
    confirmed_by NVARCHAR(100) NULL,
    confirmed_at DATETIME2     NULL,
    CONSTRAINT uq_event UNIQUE (device_id, session_id, sequence)
);

-- What was found IN one photo. One row per device type, so a zone holding
-- three cones and a sign is two rows against the same event.
--
-- This is new. The old design had device_type and count directly on
-- count_event, which worked when one photo meant one device. A zone photo of a
-- loaded truck bed shows several types at once and cannot be stored that way.
CREATE TABLE count_detection (
    detection_id INT IDENTITY(1,1) PRIMARY KEY,
    event_id     INT          NOT NULL REFERENCES count_event(event_id),
    device_type  NVARCHAR(20) NOT NULL
        CHECK (device_type IN ('cone','sign','barricade','delineator','unknown')),
    count        INT          NOT NULL,
    CONSTRAINT uq_detection UNIQUE (event_id, device_type)
);

CREATE TABLE daily_total (
    total_date   DATE         NOT NULL,
    device_type  NVARCHAR(20) NOT NULL,
    out_total    INT NOT NULL DEFAULT 0,
    in_total     INT NOT NULL DEFAULT 0,
    difference   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (total_date, device_type)
);

CREATE INDEX ix_event_session ON count_event(session_id);
CREATE INDEX ix_event_review  ON count_event(needs_review) WHERE needs_review = 1;
```

**Two clocks.** The Pi has no real-time clock — if it boots without network its time can be
badly wrong. Store `captured_at` for the record but **order and group by `received_at`**. If
`captured_at` is more than a day off `received_at`, log a warning and carry on. Never reject
an event over a bad timestamp; that would lose a real count.

**Store UTC everywhere.** Convert to Mountain Time in the dashboard only.

### The reconciliation query

This is the demo's punchline.

```sql
SELECT
    COALESCE(o.device_type, i.device_type) AS device_type,
    COALESCE(o.total, 0) AS out_total,
    COALESCE(i.total, 0) AS in_total,
    COALESCE(o.total, 0) - COALESCE(i.total, 0) AS difference
FROM
    (SELECT d.device_type, SUM(d.count) AS total
     FROM count_detection d
     JOIN count_event e ON e.event_id = d.event_id
     JOIN session s     ON s.session_id = e.session_id
     WHERE s.session_date = @date AND s.session_type = 'OUT'
       AND e.zone NOT IN ('closeup','overview')
     GROUP BY d.device_type) o
FULL OUTER JOIN
    (SELECT d.device_type, SUM(d.count) AS total
     FROM count_detection d
     JOIN count_event e ON e.event_id = d.event_id
     JOIN session s     ON s.session_id = e.session_id
     WHERE s.session_date = @date AND s.session_type = 'IN'
       AND e.zone NOT IN ('closeup','overview')
     GROUP BY d.device_type) i
  ON o.device_type = i.device_type;
```

Two things that are easy to get wrong here:

**The cross-check photo excluded in both halves.** The close-up photographs the same devices as
the wide shot (as the overview did the three zones). Leave it in the sum and every number roughly
doubles — and it doubles *plausibly*, so nobody notices until the OUT/IN difference stops making
sense. Exclude both names, not just the current one, or every legacy session doubles instead.

**`FULL OUTER JOIN`, not `INNER`.** A device type that went out and never came back is exactly
the case we exist to show, and an inner join hides it.

Also return `pending_analysis` — the number of rows in the session with `device_type IS NULL`.
The dashboard needs it to tell "0 cones" apart from "not counted yet" (§1, rule 2).

---

## 6. Vision + the Count Agent

Trigger it **inside the events function, after the row is written** — not on a Blob trigger.
Fewer moving parts, and you can see the whole request in one Application Insights trace.

**Approved device types — a closed set** (proposal §6):

```
cone · sign · barricade · delineator
```

Anything else → `device_type = "unknown"`, `needs_review = 1`. Do not let free text into the
database or the rollups fragment and the reconciliation stops summing.

Count Agent system prompt:

```
You count traffic-control devices loaded in the back of a truck.

The photo shows ONE ZONE of the truck bed (left, middle, right) or an OVERVIEW
of the whole load. Several devices are visible at once and they may be stacked,
overlapping or partly hidden behind each other.

You will receive object detections and tags from Azure AI Vision.

Reply with ONLY this JSON, no prose:
{"devices": [{"device_type": "cone", "count": 3}],
 "confidence": 0.0, "needs_review": false, "reason": "..."}

Rules:
- device_type must be one of: cone, sign, barricade, delineator, unknown
- Include one entry per type you can see. A zone with cones and a sign has two
  entries. Return an empty devices list if the zone is empty.
- count is how many of that type are visible IN THIS PHOTO
- confidence is 0.0-1.0 for the whole photo
- Set needs_review true and explain in reason when: the image is blurred or
  dark, devices are stacked or overlap so you cannot separate them, devices are
  partly out of frame, or you see a type not in the approved list
- Count only what you can actually see. Do not estimate what might be hidden
  behind the front row, and do not round to a tidy number.
- Ignore any people in the photo entirely. Never describe or count them.
- Never guess. Unsure means needs_review true.
```

Store one `count_detection` row per entry in `devices`. On re-analysis, delete that event's
detections and reinsert — never accumulate, or a retry doubles the zone.

Then, in code:

```python
if confidence < 0.80:
    needs_review = True
```

Apply that threshold **in Python, not in the prompt**. The model self-reporting a number is
weakly calibrated; the threshold is a rule and belongs where you can see it.

**Malformed JSON:** retry once, then leave the event with no detections and set
`needs_review=1, reason='agent returned invalid output'`. Never crash the request — the row and
the photo already exist and must survive.

---

## 6a. The wide/close-up cross-check

The wide shot carries the count. The close-up covers the same devices through a tighter frame.
When both captures of a session have been analysed, compare them:

```
counted_total = SUM(count) over the counted photo (wide; or left+middle+right), per device_type
check_total   = count from the cross-check photo (closeup; or overview),      per device_type
```

If they differ by more than **2 devices** for any type, set `needs_review = 1` with a reason like
`counted 12 cones, cross-check shows 7`.

**Flag the counted event, not the cross-check one.** This changed with the two-photo design. The
operator taps the amber row and corrects it; if that row is the cross-check, the headline total
does not move, because the row they just fixed was never in the total. The number stays wrong and
the human check appears to do nothing. Blame the row whose correction actually fixes the number.
(Legacy sessions have three counted rows and no way to tell which is at fault, so they keep
flagging the `overview`.)

This is the only error detection left in the system now that the beam is gone, so do not skip it.
It catches what would otherwise pass silently:

- **Something outside the load counted** — background clutter, cones on the ground beside the
  truck, a second pallet in shot. The wide shot reads high; the close-up, which cannot see them,
  does not.
- **Something inside the load missed** — occlusion, glare, a stack read as one device. The wide
  shot reads low against a tighter frame that resolves the same pile.

Both produce a confident, plausible, wrong number. The disagreement is what makes them visible.

Do **not** auto-correct to the close-up. It is a sanity check, not a better measurement — it sees
a deliberately smaller frame, so it is the one that can miss a device at the edge of the bed. It
says "these two methods disagree, a human should look", and that is all.

**The close-up must contain the entire load.** That is what makes a disagreement meaningful. If
the crop clips real devices it will read low on every single session and the flag becomes noise
that everyone learns to ignore — which is worse than not having it. `CLOSEUP_SCALE` in
`edge/camera.py` is the dial; widen it until the whole load fits.

**Vision down or out of quota:** log it, leave `device_type` NULL, return `200` anyway. Sweep
NULLs later with a timer function if you have time. If you never do, the totals are still right.

---

## 7. Build order

| Day | Do this | Done when |
|---|---|---|
| **Aug 13** | The stub in §0 | Sparshan is unblocked |
| Aug 14 | Tables created, `/api/events` writes a real row + Blob | A row appears from a real button press |
| Aug 15 | Idempotency + duplicate handling | Sending the same event twice makes one row |
| Aug 16 | Vision + Count Agent | A photo of a cone comes back `cone` |
| Aug 17 | Read API for the dashboard | Shivang's own screens have real data |
| Aug 18 | Full dry run, cold-start warming | End to end, twice, no intervention |

---

## 8. End-to-end test

Run this whole list. Each step tells you where a failure is.

1. `curl https://func-baettledger.azurewebsites.net/api/health` → `{"status":"ok"}`
2. POST without the key header → `401`
3. POST with `"zone": "wid"` → `400` (typo rejected, not silently dropped)
4. Open a session → row in `session`
5. Sparshan presses the button once → 2 rows in `count_event`, zones `wide` and `closeup`,
   2 photos in Blob
6. Replay either of them → still 2 rows, `200`
7. Wait ~10s → `count_detection` rows appear; a mixed photo gives 2+ rows for one event
8. Close the session → `status = closed`
9. `/api/today` → total equals the **wide shot alone**, close-up excluded.
   Count the cones on the table by hand and check the number matches.
10. Press twice within the same minute → **two separate sessions**, not one session with four
    events. This is the Aug 14 bug: the second capture used to be swallowed by the first
    session, which left the dashboard's OUT tab showing the previous run's photos.
11. Put something device-shaped on the ground beside the truck → wide and close-up disagree →
    `needs_review = 1`
12. Run an IN session with one device removed → `/api/today` difference is 1

Step 9 is the one to run twice. If the close-up is leaking into the sum, the number is roughly
double and still looks like a believable inventory.

---

## 9. Failure playbook

| Symptom | Do this | Demo survives? |
|---|---|---|
| Cold start, first request ~10s | Warm it with a `/api/health` call before you start | Yes |
| Duplicate events | The unique constraint absorbs them | Yes |
| Pi goes offline mid-session | Pi queues; replays on reconnect | Yes |
| Wide/close-up disagree | Flagged for review; operator confirms on screen | Yes |
| Agent returns junk | Event flagged for review, photos intact, operator counts from them | Degraded |
| Vision quota exceeded | Photos still land. Operator counts from them on screen | Degraded |
| Vision down for the whole demo | Dashboard shows "pending", not zero. Fall back to the photos | Barely |
| SQL unreachable | Everything stops. This is why we are not on serverless | No — prevent it |

Note how much the middle rows changed. Under the old beam design a Vision outage cost us
nothing; now it costs us the number and leaves only the photos and a human. **Vision is on the
critical path for the demo's headline figure.** Warm it, check the quota the morning of, and
have the review screen ready to correct from — that screen is now a fallback, not just a
nicety.

---

## 10. Out of scope

Cut deliberately, to protect August 19: Entra ID and role separation (one user now), a Blob
event-grid pipeline, batch upload, SignalR live push, retry queues beyond the Pi's own,
and reading asset-ID labels. Proposal §4 already puts most of this out of scope.

The role change is a real deviation from proposal §9 and should be said out loud in the demo,
not discovered by a guest.
