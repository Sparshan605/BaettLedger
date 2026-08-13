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

## 1. The one rule that protects the demo

**The Pi's count is the truth. Vision only says *what* was counted.**

Every beam crossing is one row, created the instant the event arrives — before Vision runs,
whether or not Vision ever succeeds. Vision fills in `device_type` afterwards.

So if Vision is slow, wrong, out of quota, or completely down, the dashboard still shows
**4 went out, 3 came back, 1 missing**. That number is the product. Nothing in your code may
let a Vision failure change it, delay it, or blank it.

Write the row first. Analyze second. Always.

---

## 2. How one cone becomes a number

1. A device passes the beam. The Pi photographs it and queues it locally.
2. The Pi `POST`s the photo + metadata to `/api/events`.
3. You check the device key, write the JPEG to Blob, and **insert the `count_event` row immediately**
   with `device_type = NULL`. Return `200`.
4. You send the photo to Azure AI Vision → objects and tags.
5. You send those to the Count Agent → `{device_type, count, confidence, needs_review, reason}`.
6. You update the row. If `confidence < 0.80`, set `needs_review = 1`.
7. The dashboard reads it.

Steps 4–6 can fail entirely and step 3 still gives a correct total.

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
{ "device_id": "baettledger-01", "session_id": "sess-2026-08-19-0815",
  "sequence": 3, "captured_at": "2026-08-19T08:17:22Z" }
```
→ `201 {"event_id": 42, "status": "accepted"}`

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
    captured_at  DATETIME2    NOT NULL,   -- Pi clock
    received_at  DATETIME2    NOT NULL DEFAULT SYSUTCDATETIME(),  -- server clock, trust this one
    photo_url    NVARCHAR(400) NULL,
    device_type  NVARCHAR(20) NULL,       -- NULL until Vision runs
    count        INT           NULL,
    confidence   DECIMAL(4,3)  NULL,
    needs_review BIT           NOT NULL DEFAULT 0,
    reason       NVARCHAR(400) NULL,
    confirmed_by NVARCHAR(100) NULL,
    confirmed_at DATETIME2     NULL,
    CONSTRAINT uq_event UNIQUE (device_id, session_id, sequence)
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
    (SELECT e.device_type, SUM(e.count) AS total
     FROM count_event e JOIN session s ON s.session_id = e.session_id
     WHERE s.session_date = @date AND s.session_type = 'OUT'
     GROUP BY e.device_type) o
FULL OUTER JOIN
    (SELECT e.device_type, SUM(e.count) AS total
     FROM count_event e JOIN session s ON s.session_id = e.session_id
     WHERE s.session_date = @date AND s.session_type = 'IN'
     GROUP BY e.device_type) i
  ON o.device_type = i.device_type;
```

`FULL OUTER JOIN`, not `INNER` — a device type that went out and never came back is exactly
the case we are trying to show, and an inner join would hide it.

Also return the raw event counts (`COUNT(*)` per session, ignoring `device_type`). Those are
the Pi-authoritative totals and they are correct even when every Vision call failed.

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
You count traffic-control devices in a photo taken at a truck tailgate.

You will receive object detections and tags from Azure AI Vision.

Reply with ONLY this JSON, no prose:
{"device_type": "...", "count": 0, "confidence": 0.0, "needs_review": false, "reason": "..."}

Rules:
- device_type must be one of: cone, sign, barricade, delineator, unknown
- count is how many of that type are visible
- confidence is 0.0-1.0
- Set needs_review true and explain in reason when: the image is blurred or dark,
  devices overlap so you cannot separate them, a device is partly out of frame,
  or the type is not in the approved list
- Ignore any people in the photo entirely. Never describe or count them.
- Never guess. Unsure means needs_review true.
```

Then, in code:

```python
if confidence < 0.80:
    needs_review = True
```

Apply that threshold **in Python, not in the prompt**. The model self-reporting a number is
weakly calibrated; the threshold is a rule and belongs where you can see it.

**Malformed JSON:** retry once, then write `device_type='unknown', needs_review=1,
reason='agent returned invalid output'`. Never crash the request — the count row already exists
and must survive.

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
3. Open a session → row in `session`
4. Sparshan presses the button → row in `count_event` within ~3s, photo in Blob
5. Same event again → still one row, `200`
6. Wait ~10s → `device_type` fills in
7. A deliberately blurry photo → `needs_review = 1`
8. Close the session → `status = closed`
9. Run an IN session with one fewer device
10. `/api/today` → difference is 1

---

## 9. Failure playbook

| Symptom | Do this | Demo survives? |
|---|---|---|
| Cold start, first request ~10s | Warm it with a `/api/health` call before you start | Yes |
| Vision quota exceeded | Nothing. Totals are unaffected | Yes |
| Agent returns junk | Row keeps `unknown`, flagged for review | Yes |
| Duplicate events | The unique constraint absorbs them | Yes |
| Pi goes offline mid-session | Pi queues; replays on reconnect | Yes |
| SQL unreachable | Everything stops. This is why we are not on serverless | No — prevent it |

---

## 10. Out of scope

Cut deliberately, to protect August 19: Entra ID and role separation (one user now), a Blob
event-grid pipeline, batch upload, SignalR live push, retry queues beyond the Pi's own,
and reading asset-ID labels. Proposal §4 already puts most of this out of scope.

The role change is a real deviation from proposal §9 and should be said out loud in the demo,
not discovered by a guest.
