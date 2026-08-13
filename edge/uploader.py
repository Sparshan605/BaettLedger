"""
Drains the local queue to the Azure API. Runs on a background thread.

The Pi is offline-first: main.py never waits for the network, and this module
catches up whenever there is one. Order per session is oldest first, so the
backend sees sequence 1 before 4.

Three things it has to get right, all of them about a flaky hotspot:

  * A request that times out may still have landed. We retry anyway — the
    backend keys on (device_id, session_id, sequence) and answers a duplicate
    with 200 (docs/api.md §4). Retrying is safe; not retrying loses data.
  * A session must exist server-side before its events, so an unsynced session
    is created on demand.
  * A session is only reported closed once every one of its photos is accepted
    (proposal §8), never before.

Timeout is deliberately long. The events endpoint runs Vision and the Count
Agent inline before it answers, so a normal successful upload can take many
seconds.
"""
import json
import logging
import threading
import time
from pathlib import Path

import requests

from edge import DEVICE_ID, config, store

log = logging.getLogger("uploader")

# The backend analyses the photo before responding; 10s would time out on
# perfectly good requests and make us re-send a 500 KB JPEG over a hotspot.
TIMEOUT_SECONDS = 30

# Health checks should fail fast — this only drives the LCD's ONLINE/OFFLINE.
HEALTH_TIMEOUT_SECONDS = 5

# Stop retrying an event that keeps failing. It stays in the database for
# inspection; it just no longer burns bandwidth on every pass.
MAX_ATTEMPTS = 10

SECONDS_BETWEEN_PASSES = 15


def is_online(base_url=None):
    """True if the API answers its health check. Drives the LCD, nothing else."""
    base_url = base_url or config.api_url()
    if not base_url:
        return False
    try:
        r = requests.get(f"{base_url}/api/health", timeout=HEALTH_TIMEOUT_SECONDS)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _headers(key):
    return {"x-device-key": key}


def ensure_session(session, base_url, key):
    """Create the session server-side if it is not there yet. True if it exists."""
    if session["synced"] >= store.SYNC_OPEN:
        return True
    body = {
        "device_id": session["device_id"],
        "session_id": session["session_id"],
        "session_type": session["session_type"],
        "opened_at": session["opened_at"],
    }
    try:
        r = requests.post(f"{base_url}/api/sessions", json=body,
                          headers=_headers(key), timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        log.warning("session %s create failed: %s", session["session_id"], exc)
        return False

    # 200 means it already existed, which is just as good as 201.
    if r.status_code in (200, 201):
        store.set_session_synced(session["session_id"], store.SYNC_OPEN)
        return True
    log.warning("session %s create returned %s: %s",
                session["session_id"], r.status_code, r.text[:200])
    return False


def upload_event(event, base_url, key):
    """POST one photo. True if the backend has it."""
    photo = Path(event["photo_path"])
    if not photo.exists():
        # The row outlived its file. Nothing to send and retrying cannot help.
        store.mark_failed(event["event_id"], "photo file missing")
        log.error("event %s: photo gone from disk (%s)", event["event_id"], photo)
        return False

    metadata = {
        "device_id": DEVICE_ID,
        "session_id": event["session_id"],
        "sequence": event["sequence"],
        "zone": event["zone"],
        "captured_at": event["captured_at"],
    }
    try:
        with photo.open("rb") as fh:
            r = requests.post(
                f"{base_url}/api/events",
                headers=_headers(key),
                data={"metadata": json.dumps(metadata)},
                files={"photo": (photo.name, fh, "image/jpeg")},
                timeout=TIMEOUT_SECONDS,
            )
    except requests.RequestException as exc:
        store.mark_failed(event["event_id"], exc)
        return False

    if r.status_code in (200, 201):
        # 200 = the backend already had it. Same outcome for us.
        store.mark_uploaded(event["event_id"])
        return True

    store.mark_failed(event["event_id"], f"HTTP {r.status_code}: {r.text[:200]}")
    return False


def close_session_remote(session, base_url, key):
    try:
        r = requests.post(
            f"{base_url}/api/sessions/{session['session_id']}/close",
            json={"closed_at": session["closed_at"]},
            headers=_headers(key), timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        log.warning("close %s failed: %s", session["session_id"], exc)
        return False
    if r.status_code == 200:
        store.set_session_synced(session["session_id"], store.SYNC_CLOSED)
        return True
    log.warning("close %s returned %s", session["session_id"], r.status_code)
    return False


def drain(base_url=None, key=None, limit=None):
    """One pass over the queue. Returns a summary dict.

    Never raises: a background thread that dies silently is worse than one that
    logs and tries again in fifteen seconds.
    """
    base_url = base_url or config.api_url()
    key = key or config.device_key()
    result = {"uploaded": 0, "failed": 0, "skipped": 0, "closed": 0, "online": False}

    if not base_url or not key:
        log.debug("not configured; nothing to do")
        return result

    pending = store.pending(limit=limit)
    sessions = {}

    for event in pending:
        if event["attempts"] >= MAX_ATTEMPTS:
            result["skipped"] += 1
            continue

        session_id = event["session_id"]
        if session_id not in sessions:
            sessions[session_id] = store.get_session(session_id)
        session = sessions[session_id]

        if not session or not ensure_session(session, base_url, key):
            result["failed"] += 1
            continue
        # ensure_session may have just flipped it; keep our copy honest so the
        # next event in this pass does not POST the session again.
        session["synced"] = max(session["synced"], store.SYNC_OPEN)

        if upload_event(event, base_url, key):
            result["uploaded"] += 1
        else:
            result["failed"] += 1

    for session in store.sessions_awaiting_close():
        if close_session_remote(session, base_url, key):
            result["closed"] += 1

    result["online"] = result["uploaded"] > 0 or is_online(base_url)
    return result


def run_forever(stop_event=None, interval=SECONDS_BETWEEN_PASSES):
    """Drain, sleep, repeat, until stop_event is set."""
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            summary = drain()
            if summary["uploaded"] or summary["failed"]:
                log.info("uploaded %(uploaded)s failed %(failed)s closed %(closed)s",
                         summary)
        except Exception:  # never let the thread die
            log.exception("drain pass failed")
        stop_event.wait(interval)


def start(interval=SECONDS_BETWEEN_PASSES):
    """Start the background thread. Returns (thread, stop_event)."""
    stop_event = threading.Event()
    thread = threading.Thread(target=run_forever, args=(stop_event, interval),
                              name="uploader", daemon=True)
    thread.start()
    return thread, stop_event


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if "--live" in sys.argv:
        url = config.api_url()
        print(f"API_URL   : {url or '(unset)'}")
        print(f"configured: {config.is_configured()}")
        if not config.is_configured():
            print("\nNot configured. cp .env.example .env and fill it in.")
            sys.exit(1)
        print(f"online    : {is_online()}")
        print(f"pending   : {store.pending_count()}")
        print("\ndraining once ...")
        print(drain())
        print(f"pending now: {store.pending_count()}")
        sys.exit(0)

    print("Run with --live to drain against the real API.")
    print("Run edge/uploader_selftest.py to exercise it against a mock server.")
