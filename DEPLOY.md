# v3 — two photos per press

An inventory is now **two photos of one capture**: `wide` (the uncropped frame,
which carries the count) and `closeup` (the same load through a tighter frame,
counted independently as a cross-check and never added to the total).

This replaced the v2 three-zone split (`left`/`middle`/`right` summed, plus an
`overview` cross-check). Thirds tiled the frame exactly, so the sum was valid by
construction, but a device straddling a boundary got sliced in half in two crops
and every press put four photos through Vision. See docs/api.md §1.

**Sessions captured under v2 are still in the database and still total
correctly.** The old zone names remain valid everywhere; `db.COUNT_ZONES` and
`isCheckZone()` in `src/types.ts` are what decide whether a row is arithmetic or
evidence.

## Do this, in this order

The order matters. Steps 1 and 2 must both land **before** the Pi sends its
first `wide` photo, or the database rejects it, `/api/events` answers 500, and
the uploader queues behind a request that can never succeed. Nothing is lost —
but nothing reaches the dashboard either.

### 1. Migrate the database — NOT `run_schema.py`

`run_schema.py` drops every table. Do not point it at the live database. Use the
migration, which touches no data and only widens the `zone` CHECK constraint:

```bash
python migrate_zones.py
```

It prints the zones currently in `count_event`, swaps the constraint, then
inserts and deletes a throwaway `wide` row to prove the new value is actually
accepted. Safe to run twice.

### 2. Deploy the Function App

Actions tab → **Deploy Function App** → Run workflow. It is manual on purpose
until after the Aug 19 demo (see the comment at the top of the workflow). The
workflow verifies `/api/health` answers 200 before it reports success.

### 3. Update the Pi

```bash
ssh -i ~/.ssh/id_ed25519_roadledger baettledger@raspberrypi.local
cd ~/BaettLedger && git pull && sudo systemctl restart baettledger
```

### 4. Check the crop before you rely on it

```bash
python3 -m edge.camera /tmp/check.jpg
```

Then **look at `/tmp/check_closeup.jpg`**. It must still contain the *entire*
load. If it clips real devices, the cross-check will read low on every session
and flag every one of them — raise `CLOSEUP_SCALE` in `edge/camera.py` until the
whole load fits.

### 5. Re-run the end-to-end test in api.md §8

12 steps now. Step 5 (one press → two rows), step 9 (total equals the wide shot
alone), and step 10 (two presses in one minute → two separate sessions) are the
changed behaviour.

## Also fixed in this update

**Two presses inside the same minute collided.** `session_id` stopped at
`HH:MM`, so the second press reused the first session's row — direction and all.
On Aug 14 a fresh OUT capture was filed as sequences 5–8 of the preceding IN
session, which left the dashboard's OUT tab showing the *previous* run's photos
while IN showed both new ones. The id now carries seconds, and a genuine
collision takes the next id instead of silently merging. `python3 -m edge.store`
covers it.

**The cross-check flagged the wrong row.** It flagged the cross-check photo — so
an operator correcting the amber row on stage would watch the headline total not
move, because the row they just fixed was never in the total. It now flags the
counted photo. Legacy sessions have three counted rows and no way to tell which
is at fault, so they keep flagging the `overview`.

## Local checks (no Azure needed)

```bash
python3 -m edge.store              # queue, sessions, direction, collisions
python3 -m edge.uploader_selftest  # uploads, retries, duplicates, offline
npm run build                      # dashboard typecheck + bundle
```
