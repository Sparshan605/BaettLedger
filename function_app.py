"""
BaettLedger API — Azure Function App (Python 3.11, Consumption plan).
v2, zone-based architecture (Aug 13 rewrite — the beam sensor is gone).
Owner: Shivang. Source of truth for all shapes: docs/api.md, docs/dashboard.md.

A session now produces FOUR photos: left, middle, right, overview. Each photo
(count_event row) can hold several device types at once (count_detection
rows). Vision/Agent failure can cost us the number but never the photo, and
never a silent zero (api.md §1).

Routes:
  Pi-facing:        GET /api/health, POST /api/sessions, POST /api/events,
                     POST /api/sessions/{session_id}/close
  Dashboard-facing:  GET /api/today, GET /api/events, GET /api/review,
                     POST /api/events/{event_id}/confirm
"""
import decimal
import json
import logging
import os
from datetime import date, datetime, timezone

import azure.functions as func

import db
import blob
import vision
import agent

app = func.FunctionApp()


def _encode(value):
    """JSON encoder for the types pyodbc hands back.

    This used to be plain `default=str`, which silently turned SQL DECIMAL into
    a quoted string: confidence came out as "0.870" instead of 0.87. The
    dashboard called .toFixed() on it, threw, and rendered a blank page — with
    the only clue being "h.toFixed is not a function" in the console.

    Numbers stay numbers, timestamps become ISO 8601 in UTC so JavaScript's
    Date can parse them without relying on non-standard formats.
    """
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, datetime):
        stamped = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return stamped.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _json(body: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body, default=_encode), status_code=status_code,
                              mimetype="application/json")


def _check_device_key(req: func.HttpRequest) -> bool:
    return req.headers.get("x-device-key") == os.environ["DEVICE_KEY"]


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _json({"status": "ok"})


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------
@app.route(route="sessions", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def create_session(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_device_key(req):
        return _json({"error": "bad key"}, 401)

    try:
        payload = req.get_json()
        device_id = payload["device_id"]
        session_id = payload["session_id"]
        session_type = payload["session_type"]
        opened_at = _parse_iso(payload["opened_at"])
    except (ValueError, KeyError) as e:
        return _json({"error": f"bad payload: {e}"}, 400)

    status, _ = db.upsert_session(device_id, session_id, session_type, opened_at)
    code = 201 if status == "created" else 200
    return _json({"session_id": session_id, "status": "open"}, code)


# ---------------------------------------------------------------------------
# POST /api/events  — one of the four zone photos. Write the row FIRST.
# ---------------------------------------------------------------------------
@app.route(route="events", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def create_event(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_device_key(req):
        return _json({"error": "bad key"}, 401)

    try:
        metadata_raw = req.form.get("metadata")
        photo_file = req.files.get("photo")
        if not metadata_raw or not photo_file:
            return _json({"error": "expected multipart form with 'metadata' and 'photo'"}, 400)

        metadata = json.loads(metadata_raw)
        device_id = metadata["device_id"]
        session_id = metadata["session_id"]
        sequence = int(metadata["sequence"])
        zone = metadata["zone"]
        captured_at = _parse_iso(metadata["captured_at"])
        photo_bytes = photo_file.read()
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return _json({"error": f"bad payload: {e}"}, 400)

    # api.md §3: an invalid zone must be rejected outright, not silently
    # dropped — a typo'd zone would undercount the whole inventory.
    if zone not in db.APPROVED_ZONES:
        return _json({"error": f"zone must be one of {sorted(db.APPROVED_ZONES)}"}, 400)

    # Write the JPEG to Blob, insert the row immediately, analyzed_at=NULL.
    # This must succeed and return 201/200 whether or not Vision ever runs
    # (api.md §1: a failure may cost the number, never the evidence).
    photo_url = blob.upload_photo(device_id, session_id, sequence, photo_bytes)
    status, event_id, clock_skew = db.insert_event(
        device_id, session_id, sequence, zone, captured_at, photo_url
    )

    if clock_skew:
        logging.warning("captured_at more than a day off received_at for event %s", event_id)

    if status == "duplicate":
        # Same (device, session, sequence) seen again — correct behaviour,
        # not a bug. No second row, no second photo, no second Vision call.
        return _json({"event_id": event_id, "status": "accepted"}, 200)

    # Vision -> Count Agent -> save detections -> zone/overview cross-check.
    # Any failure here must never affect the 201 already implied by the row
    # existing. On vision failure, deliberately do NOT call save_detections,
    # so analyzed_at stays NULL and the dashboard shows "pending", not "0".
    try:
        # Vision is a hint now, not the input — the Count Agent reads the JPEG
        # itself (agent.py). A Vision outage therefore costs a hint and nothing
        # more, where it used to mean no count at all.
        vision_result = vision.analyze_image(photo_bytes)
        result = agent.count_devices(photo_bytes, vision_result)
        if result["devices"] is not None:
            db.save_detections(
                event_id, result["devices"], result["confidence"],
                result["needs_review"], result["reason"],
            )
            db.run_zone_overview_cross_check(session_id)
        else:
            logging.warning("Count Agent unavailable for event %s; leaving unanalyzed", event_id)
    except Exception as e:
        logging.error("Analysis pipeline failed for event %s: %s", event_id, e)
        # Row and photo already exist with analyzed_at=NULL — recoverable from
        # the photo alone even if this whole pipeline is down (api.md §1).

    return _json({"event_id": event_id, "status": "accepted"}, 201)


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/close
# ---------------------------------------------------------------------------
@app.route(route="sessions/{session_id}/close", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def close_session(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_device_key(req):
        return _json({"error": "bad key"}, 401)

    session_id = req.route_params.get("session_id")
    try:
        payload = req.get_json()
        closed_at = _parse_iso(payload["closed_at"])
    except (ValueError, KeyError) as e:
        return _json({"error": f"bad payload: {e}"}, 400)

    total_events = db.close_session(session_id, closed_at)
    return _json({"session_id": session_id, "status": "closed", "total_events": total_events})


# ---------------------------------------------------------------------------
# GET /api/today?date=YYYY-MM-DD
# ---------------------------------------------------------------------------
@app.route(route="today", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_today(req: func.HttpRequest) -> func.HttpResponse:
    date_str = req.params.get("date") or datetime.now(timezone.utc).date().isoformat()
    return _json(db.get_today(date_str))


# ---------------------------------------------------------------------------
# GET /api/events?session_id=...
# ---------------------------------------------------------------------------
@app.route(route="events", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def list_events(req: func.HttpRequest) -> func.HttpResponse:
    session_id = req.params.get("session_id")
    if not session_id:
        return _json({"error": "session_id required"}, 400)
    return _json({"events": blob.with_photo_links(db.get_events(session_id))})


# ---------------------------------------------------------------------------
# GET /api/review
# ---------------------------------------------------------------------------
@app.route(route="review", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_review(req: func.HttpRequest) -> func.HttpResponse:
    return _json({"events": blob.with_photo_links(db.get_review_queue())})


# ---------------------------------------------------------------------------
# POST /api/events/{event_id}/confirm
# ---------------------------------------------------------------------------
@app.route(route="events/{event_id}/confirm", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def confirm_event(req: func.HttpRequest) -> func.HttpResponse:
    event_id = req.route_params.get("event_id")
    try:
        payload = req.get_json()
        devices = payload["devices"]  # list of {device_type, count}; [] zeroes the zone
    except (ValueError, KeyError) as e:
        return _json({"error": f"bad payload: {e}"}, 400)

    try:
        confirmed_at = db.confirm_event(int(event_id), devices)
    except ValueError as e:
        return _json({"error": str(e)}, 400)

    return _json({"event_id": int(event_id), "confirmed_at": confirmed_at})
