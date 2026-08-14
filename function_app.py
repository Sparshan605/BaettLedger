"""
BaettLedger API — Azure Function App (Python 3.11, Consumption plan).
Owner: Shivang. Source of truth for all shapes: docs/api.md.

Routes:
  Pi-facing:        GET /api/health, POST /api/sessions, POST /api/events,
                     POST /api/sessions/{session_id}/close
  Dashboard-facing:  GET /api/today, GET /api/events, GET /api/review,
                     POST /api/events/{event_id}/confirm
"""
import json
import logging
import os
from datetime import datetime, timezone

import azure.functions as func

import db
import blob
import vision
import agent

app = func.FunctionApp()


def _json(body: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(body, default=str), status_code=status_code,
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
# POST /api/events  — the important one. Write the row FIRST. Analyze second.
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
        captured_at = _parse_iso(metadata["captured_at"])
        photo_bytes = photo_file.read()
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return _json({"error": f"bad payload: {e}"}, 400)

    # Step 3 (api.md §2): write the JPEG to Blob, insert the row immediately.
    # This must succeed and return 201/200 whether or not Vision ever runs.
    photo_url = blob.upload_photo(device_id, session_id, sequence, photo_bytes)
    status, event_id, clock_skew = db.insert_event(device_id, session_id, sequence, captured_at, photo_url)

    if clock_skew:
        logging.warning("captured_at more than a day off received_at for event %s", event_id)

    if status == "duplicate":
        # Same (device, session, sequence) seen again — this is correct behaviour,
        # not a bug. No second row, no second photo, no second Vision call.
        return _json({"event_id": event_id, "status": "accepted"}, 200)

    # Steps 4-6 (api.md §2): Vision -> Count Agent -> update row.
    # Any failure here must never affect the 201 already implied by the row existing.
    try:
        vision_result = vision.analyze_image(photo_bytes)
        result = agent.count_devices(vision_result)
        db.update_event_analysis(
            event_id,
            result["device_type"], result["count"], result["confidence"],
            result["needs_review"], result["reason"],
        )
    except Exception as e:
        logging.error("Analysis pipeline failed for event %s: %s", event_id, e)
        # Row already exists with device_type=NULL — totals are still correct.

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
    return _json({"events": db.get_events(session_id)})


# ---------------------------------------------------------------------------
# GET /api/review
# ---------------------------------------------------------------------------
@app.route(route="review", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_review(req: func.HttpRequest) -> func.HttpResponse:
    return _json({"events": db.get_review_queue()})


# ---------------------------------------------------------------------------
# POST /api/events/{event_id}/confirm
# ---------------------------------------------------------------------------
@app.route(route="events/{event_id}/confirm", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def confirm_event(req: func.HttpRequest) -> func.HttpResponse:
    event_id = req.route_params.get("event_id")
    try:
        payload = req.get_json()
        device_type = payload["device_type"]
        count = int(payload["count"])
    except (ValueError, KeyError) as e:
        return _json({"error": f"bad payload: {e}"}, 400)

    try:
        confirmed_at = db.confirm_event(int(event_id), device_type, count)
    except ValueError as e:
        return _json({"error": str(e)}, 400)

    return _json({"event_id": int(event_id), "confirmed_at": confirmed_at})
