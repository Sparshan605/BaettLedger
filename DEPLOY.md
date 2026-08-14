# v2 — what changed and what to do

The beam sensor broke, so Sparshan redesigned the capture: one session now
produces FOUR photos (left, middle, right, overview) instead of one photo
per device. See docs/api.md §1 for the full rationale.

## Files changed in this update
- `schema.sql` — count_event no longer has device_type/count; new
  count_detection table (one row per device type found in a photo); new
  `zone` and `analyzed_at` columns
- `db.py` — rewritten: insert_event takes `zone`, new save_detections(),
  new zone/overview cross-check (run_zone_overview_cross_check), confirm_event
  now takes a `devices` list
- `agent.py` — new system prompt (returns a `devices` list per photo, not a
  single device_type/count), threshold logic unchanged
- `function_app.py` — /api/events now validates `zone` (400 on invalid),
  triggers the cross-check after saving detections; /api/events/{id}/confirm
  now takes `{"devices": [...]}`
- `vision.py`, `blob.py` — unchanged, no edits needed

## Do this before deploying

1. **Drop and recreate the database** — this schema is not backward
   compatible with the old one. If `sql-baettledger` already has the old
   tables from a previous run:
   ```sql
   DROP TABLE IF EXISTS count_detection;
   DROP TABLE IF EXISTS count_event;
   DROP TABLE IF EXISTS daily_total;
   DROP TABLE IF EXISTS session;
   ```
   Then run the new `schema.sql` in full.

2. **Redeploy the function code**:
   ```bash
   func azure functionapp publish func-baettledger
   ```
   (or however deploy is being handled on your team — confirm with Protsahan.)

3. **Re-run the end-to-end test in api.md §8** — it now has 11 steps instead
   of 10, including the zone-typo rejection test and the zone/overview
   mismatch test. Steps 5, 7, 9, and 10 are new/changed behaviour.

## Quick local check after updating local.settings.json

```powershell
curl.exe http://localhost:7071/api/health

curl.exe -X POST http://localhost:7071/api/events -H "x-device-key: <DEVICE_KEY>"
# -> 400 "expected multipart form..." (unchanged)
```

To really exercise the new path you need a real multipart POST with a `zone`
field — worth writing a tiny test script rather than fighting curl's syntax
for multipart forms on Windows. Ask me if you want one.
