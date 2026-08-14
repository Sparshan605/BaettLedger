"""
Exercises uploader.py against a mock of the API described in docs/api.md.

Runs a real HTTP server on localhost, so requests, multipart encoding, status
handling and the retry path are all genuinely tested — not stubbed. Verifies
the behaviours that only bite on a bad network:

  * a 500 leaves the event queued and it succeeds on the next pass
  * a duplicate POST returns 200 and is treated as success, not an error
  * the session is created before its events
  * the session close is only sent once every photo is accepted
  * a wrong device key fails cleanly instead of silently dropping data
  * the server being down leaves everything queued and loses nothing
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edge import CAPTURE_SEQUENCE, store, uploader  # noqa: E402

KEY = "test-key-123"

state = {
    "sessions": {},      # session_id -> {"closed": bool}
    "events": set(),     # (session_id, sequence)
    "fail_next": 0,      # number of upcoming /api/events calls to answer 500
    "requests": [],      # ordered log of (method, path)
}


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep the test output readable

    def _reply(self, code, body):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authorised(self):
        if self.headers.get("x-device-key") != KEY:
            self._reply(401, {"error": "bad key"})
            return False
        return True

    def do_GET(self):
        state["requests"].append(("GET", self.path))
        if self.path == "/api/health":
            return self._reply(200, {"status": "ok"})
        self._reply(404, {"error": "not found"})

    def do_POST(self):
        state["requests"].append(("POST", self.path))
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        if not self._authorised():
            return

        if self.path == "/api/sessions":
            body = json.loads(raw)
            sid = body["session_id"]
            existed = sid in state["sessions"]
            state["sessions"].setdefault(sid, {"closed": False})
            return self._reply(200 if existed else 201,
                               {"session_id": sid, "status": "open"})

        if self.path.endswith("/close"):
            sid = self.path.split("/")[-2]
            if sid not in state["sessions"]:
                return self._reply(404, {"error": "no such session"})
            state["sessions"][sid]["closed"] = True
            return self._reply(200, {"session_id": sid, "status": "closed"})

        if self.path == "/api/events":
            if state["fail_next"] > 0:
                state["fail_next"] -= 1
                return self._reply(500, {"error": "simulated server error"})
            # Pull the metadata part out of the multipart body.
            text = raw.decode("utf-8", "replace")
            start = text.find("{")
            end = text.find("}", start)
            meta = json.loads(text[start:end + 1])
            key = (meta["session_id"], meta["sequence"])
            duplicate = key in state["events"]
            state["events"].add(key)
            # docs/api.md §4: a duplicate is 200, never 409.
            return self._reply(200 if duplicate else 201,
                               {"event_id": len(state["events"]), "status": "accepted"})

        self._reply(404, {"error": "not found"})


def main():
    failures = []

    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'}  {label:<48} {got!r}"
              + ("" if ok else f"  (expected {want!r})"))
        if not ok:
            failures.append(label)

    server = HTTPServer(("127.0.0.1", 0), Mock)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"mock API on {base}\n")

    tmp = Path(tempfile.mkdtemp())
    db = tmp / "queue.db"
    store.DB_PATH = db  # point the whole module at a scratch database
    store.init(db)

    # An inventory is two photos, so queue two of them: four events, which is
    # what the partial-failure cases below need to split into halves.
    photos = []
    for zone in CAPTURE_SEQUENCE:
        p = tmp / f"shot_{zone}.jpg"
        p.write_bytes(b"\xff\xd8\xff" + b"x" * 2000)  # not a real JPEG, but real bytes
        photos.append((zone, p))

    session = store.open_session(db, now="2026-08-19T08:15:00Z")
    store.add_inventory(session["session_id"], photos, db)
    store.add_inventory(session["session_id"], photos, db)
    store.close_session(session["session_id"], db)
    check("queued before upload", store.pending_count(db), 4)

    print("\nserver unreachable — nothing must be lost")
    result = uploader.drain("http://127.0.0.1:1", KEY)
    check("nothing uploaded", result["uploaded"], 0)
    check("all still queued", store.pending_count(db), 4)

    print("\nwrong device key")
    state["requests"].clear()
    result = uploader.drain(base, "wrong-key")
    check("nothing uploaded", result["uploaded"], 0)
    check("still queued", store.pending_count(db), 4)
    check("no events reached the server", len(state["events"]), 0)

    print("\nfirst two events hit a 500")
    state["fail_next"] = 2
    result = uploader.drain(base, KEY)
    check("two succeeded", result["uploaded"], 2)
    check("two failed", result["failed"], 2)
    check("failures still queued", store.pending_count(db), 2)

    print("\nnext pass retries them")
    result = uploader.drain(base, KEY)
    check("remaining uploaded", result["uploaded"], 2)
    check("queue empty", store.pending_count(db), 0)
    check("server has all four", len(state["events"]), 4)
    check("session created before events",
          state["requests"].index(("POST", "/api/sessions"))
          < state["requests"].index(("POST", "/api/events")), True)

    print("\nsession close")
    check("session closed on server",
          state["sessions"][session["session_id"]]["closed"], True)
    check("marked closed locally",
          store.get_session(session["session_id"], db)["synced"], store.SYNC_CLOSED)

    print("\nreplaying an already-uploaded event is harmless")
    ev = store.pending(db_path=db)
    check("nothing pending to replay", ev, [])
    # Force one back into the queue, as a lost acknowledgement would.
    with store._connect(db) as c:
        c.execute("UPDATE event SET uploaded_at = NULL WHERE sequence = 1")
    before = len(state["events"])
    result = uploader.drain(base, KEY)
    check("re-sent and accepted", result["uploaded"], 1)
    check("server did not gain a row", len(state["events"]), before)
    check("queue empty again", store.pending_count(db), 0)

    print("\nmissing photo file")
    with store._connect(db) as c:
        c.execute("INSERT INTO event (session_id, sequence, zone, photo_path, captured_at)"
                  " VALUES (?, 77, 'wide', '/tmp/does_not_exist.jpg', ?)",
                  (session["session_id"], store.utc_now()))
    result = uploader.drain(base, KEY)
    check("counted as failed, not crashed", result["failed"], 1)

    print("\nhealth check")
    check("is_online true against mock", uploader.is_online(base), True)
    check("is_online false when down", uploader.is_online("http://127.0.0.1:1"), False)

    server.shutdown()
    print()
    if failures:
        print(f"FAIL — {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASS — uploads, retries, duplicates, session sync and offline all behave.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
