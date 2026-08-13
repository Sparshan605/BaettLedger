"""
The local queue. Every photo is recorded here before anything is uploaded.

This is what makes the Pi offline-first (proposal §8): captures land in SQLite
immediately, the LCD shows OFFLINE when the API is unreachable, and uploader.py
replays the queue on reconnect. A session cannot close until the queue drains.

Two decisions came out of losing power mid-session on Aug 13:

  * WAL journal mode, so an interrupted write cannot corrupt the database.
  * One commit per capture, never a batch. At two inventories a day the cost is
    nothing, and it means a power cut loses at most the photo being written —
    never a queue entry that was already acknowledged on the LCD.

Connections are opened per operation rather than shared. uploader.py runs on a
background thread while main.py writes from the foreground, and a shared
sqlite3 connection across threads is a bug waiting for the worst moment.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from edge import DATA_DIR, DEVICE_ID

DB_PATH = DATA_DIR / "queue.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
    session_id   TEXT PRIMARY KEY,
    device_id    TEXT NOT NULL,
    session_type TEXT NOT NULL CHECK (session_type IN ('OUT','IN')),
    session_date TEXT NOT NULL,
    opened_at    TEXT NOT NULL,
    closed_at    TEXT,
    synced       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS event (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES session(session_id),
    sequence    INTEGER NOT NULL,
    zone        TEXT NOT NULL,
    photo_path  TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    uploaded_at TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    -- Mirrors the server's idempotency key (docs/api.md §4). Assigned once and
    -- never changed, so a replay after a timeout reuses the same key and the
    -- backend recognises the duplicate instead of double-counting.
    UNIQUE (session_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_event_pending
    ON event(uploaded_at) WHERE uploaded_at IS NULL;
"""


def utc_now():
    """Timestamp in the exact format the API parses (docs/api.md §3)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _connect(db_path=None):
    """Open, commit, close. One connection per operation — see module docstring."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # WAL survives an unclean shutdown; the setting persists in the file, so
        # this is a no-op after the first call.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(db_path=None):
    """Create the tables if they are not there. Safe to call every boot."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def next_direction(db_path=None, today=None):
    """OUT or IN for the next session, with no operator input.

    The morning load is OUT and the evening recovery is IN, so the rule is
    simply: if today has more OUT sessions than IN, the next one is IN.
    Otherwise OUT. That handles the normal day, a repeated run after a mistake,
    and the first session after midnight, without a button to get wrong.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _connect(db_path) as conn:
        row = conn.execute(
            """SELECT
                 SUM(session_type = 'OUT') AS outs,
                 SUM(session_type = 'IN')  AS ins
               FROM session WHERE session_date = ?""",
            (today,),
        ).fetchone()
    outs = row["outs"] or 0
    ins = row["ins"] or 0
    return "IN" if outs > ins else "OUT"


def open_session(db_path=None, session_type=None, now=None):
    """Start a session. Returns its row.

    session_type defaults to next_direction(); pass it explicitly only to
    override, e.g. from a rehearsal script.
    """
    now = now or utc_now()
    session_date = now[:10]
    session_type = session_type or next_direction(db_path, today=session_date)
    session_id = f"sess-{session_date}-{now[11:13]}{now[14:16]}"

    with _connect(db_path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO session
                 (session_id, device_id, session_type, session_date, opened_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, DEVICE_ID, session_type, session_date, now),
        )
        return dict(conn.execute(
            "SELECT * FROM session WHERE session_id = ?", (session_id,)
        ).fetchone())


def close_session(session_id, db_path=None, now=None):
    """Mark a session closed. Returns the number of events in it.

    Does NOT check the queue. main.py must wait for pending_count() to reach
    zero before calling this — proposal §8 requires a session not close on
    incomplete data, and that wait belongs where the LCD can show progress.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE session SET closed_at = ? WHERE session_id = ? AND closed_at IS NULL",
            (now or utc_now(), session_id),
        )
        return conn.execute(
            "SELECT COUNT(*) AS n FROM event WHERE session_id = ?", (session_id,)
        ).fetchone()["n"]


def open_sessions(db_path=None):
    """Sessions that were never closed — a power cut mid-inventory leaves one."""
    with _connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM session WHERE closed_at IS NULL ORDER BY opened_at"
        )]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def add(session_id, zone, photo_path, db_path=None, captured_at=None):
    """Queue one photo. Returns (event_id, sequence).

    sequence continues from whatever the session already has, so a second
    inventory in the same session gets 5-8 rather than colliding with 1-4.
    """
    with _connect(db_path) as conn:
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM event WHERE session_id = ?",
            (session_id,),
        ).fetchone()["n"]
        cur = conn.execute(
            """INSERT INTO event (session_id, sequence, zone, photo_path, captured_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, sequence, zone, str(photo_path), captured_at or utc_now()),
        )
        return cur.lastrowid, sequence


def add_inventory(session_id, frames, db_path=None, captured_at=None):
    """Queue all four images from one capture. Returns the rows added.

    `frames` is what camera.split_zones() returns: [(zone, path), ...].
    One timestamp is shared across all four because they came from a single
    shutter — recording four different times would imply four captures.
    """
    captured_at = captured_at or utc_now()
    return [
        {"event_id": event_id, "sequence": sequence, "zone": zone, "photo_path": str(path)}
        for zone, path in frames
        for event_id, sequence in [add(session_id, zone, path, db_path, captured_at)]
    ]


def pending(limit=None, db_path=None):
    """Events not yet uploaded, oldest first. uploader.py drains this."""
    sql = ("SELECT * FROM event WHERE uploaded_at IS NULL "
           "ORDER BY event_id" + (" LIMIT ?" if limit else ""))
    with _connect(db_path) as conn:
        rows = conn.execute(sql, (limit,) if limit else ()).fetchall()
    return [dict(r) for r in rows]


def pending_count(db_path=None, session_id=None):
    """How many events are still waiting. The LCD shows this while draining."""
    sql = "SELECT COUNT(*) AS n FROM event WHERE uploaded_at IS NULL"
    params = ()
    if session_id:
        sql += " AND session_id = ?"
        params = (session_id,)
    with _connect(db_path) as conn:
        return conn.execute(sql, params).fetchone()["n"]


def mark_uploaded(event_id, db_path=None, now=None):
    """Called after the API returns 2xx. Idempotent."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE event SET uploaded_at = ?, last_error = NULL WHERE event_id = ?",
            (now or utc_now(), event_id),
        )


def mark_failed(event_id, error, db_path=None):
    """Record a failed attempt. The row stays pending and will be retried."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE event SET attempts = attempts + 1, last_error = ? WHERE event_id = ?",
            (str(error)[:400], event_id),
        )


def session_totals(session_id, db_path=None):
    """Counts for the LCD: how many photos taken, how many still queued."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS captured,
                      SUM(uploaded_at IS NULL) AS pending
               FROM event WHERE session_id = ?""",
            (session_id,),
        ).fetchone()
    return {"captured": row["captured"], "pending": row["pending"] or 0}


if __name__ == "__main__":
    import sys
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "selftest.db"
    failures = []

    def check(label, got, want):
        ok = got == want
        print(f"  {'ok  ' if ok else 'FAIL'}  {label:<44} {got!r}"
              + ("" if ok else f"  (expected {want!r})"))
        if not ok:
            failures.append(label)

    print(f"self-test against {tmp}\n")
    init(tmp)

    print("journal mode")
    with _connect(tmp) as c:
        check("WAL enabled", c.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    print("\ndirection with no history")
    check("first session of the day is OUT", next_direction(tmp, today="2026-08-19"), "OUT")

    print("\nOUT session, one inventory")
    s1 = open_session(tmp, now="2026-08-19T08:15:00Z")
    check("session_type", s1["session_type"], "OUT")
    check("session_id format", s1["session_id"], "sess-2026-08-19-0815")

    frames = [("left", "/tmp/a_left.jpg"), ("middle", "/tmp/a_middle.jpg"),
              ("right", "/tmp/a_right.jpg"), ("overview", "/tmp/a.jpg")]
    rows = add_inventory(s1["session_id"], frames, tmp, captured_at="2026-08-19T08:16:00Z")
    check("four rows queued", len(rows), 4)
    check("sequences 1-4", [r["sequence"] for r in rows], [1, 2, 3, 4])
    check("zones in order", [r["zone"] for r in rows],
          ["left", "middle", "right", "overview"])
    check("one shared timestamp", len({
        e["captured_at"] for e in pending(db_path=tmp)}), 1)

    print("\nsecond inventory continues the numbering")
    rows2 = add_inventory(s1["session_id"], frames, tmp)
    check("sequences 5-8", [r["sequence"] for r in rows2], [5, 6, 7, 8])

    print("\nqueue drain")
    check("pending", pending_count(tmp), 8)
    mark_uploaded(rows[0]["event_id"], tmp)
    mark_uploaded(rows[1]["event_id"], tmp)
    check("after two uploads", pending_count(tmp), 6)
    check("oldest pending first", pending(limit=1, db_path=tmp)[0]["event_id"],
          rows[2]["event_id"])

    print("\nfailure handling")
    mark_failed(rows[2]["event_id"], "connection timed out", tmp)
    mark_failed(rows[2]["event_id"], "connection timed out", tmp)
    still = [e for e in pending(db_path=tmp) if e["event_id"] == rows[2]["event_id"]][0]
    check("attempts counted", still["attempts"], 2)
    check("still pending after failures", still["uploaded_at"], None)
    mark_uploaded(rows[2]["event_id"], tmp)
    after = [e for e in pending(db_path=tmp) if e["event_id"] == rows[2]["event_id"]]
    check("gone from queue once uploaded", after, [])
    mark_uploaded(rows[2]["event_id"], tmp)
    check("mark_uploaded is idempotent", pending_count(tmp), 5)

    print("\nsimulated power cut: reopen the database cold")
    before = pending_count(tmp)
    with _connect(tmp) as c:
        c.execute("INSERT INTO event (session_id, sequence, zone, photo_path, captured_at)"
                  " VALUES (?, 99, 'left', '/tmp/x.jpg', ?)", (s1["session_id"], utc_now()))
    check("committed row survives reopen", pending_count(tmp), before + 1)

    print("\nduplicate protection")
    try:
        with _connect(tmp) as c:
            c.execute("INSERT INTO event (session_id, sequence, zone, photo_path, captured_at)"
                      " VALUES (?, 99, 'left', '/tmp/x.jpg', ?)", (s1["session_id"], utc_now()))
        check("second (session, sequence) rejected", "accepted", "rejected")
    except sqlite3.IntegrityError:
        check("second (session, sequence) rejected", "rejected", "rejected")

    print("\nclosing, then the IN session")
    check("session totals", session_totals(s1["session_id"], tmp)["captured"], 9)
    check("open sessions before close", len(open_sessions(tmp)), 1)
    close_session(s1["session_id"], tmp, now="2026-08-19T08:40:00Z")
    check("open sessions after close", len(open_sessions(tmp)), 0)
    check("next direction is IN", next_direction(tmp, today="2026-08-19"), "IN")

    s2 = open_session(tmp, now="2026-08-19T16:30:00Z")
    check("evening session is IN", s2["session_type"], "IN")
    check("its sequences restart at 1",
          add_inventory(s2["session_id"], frames, tmp)[0]["sequence"], 1)
    close_session(s2["session_id"], tmp)
    check("after OUT and IN, next is OUT", next_direction(tmp, today="2026-08-19"), "OUT")

    print("\na different day starts fresh")
    check("tomorrow is OUT", next_direction(tmp, today="2026-08-20"), "OUT")

    print()
    if failures:
        print(f"FAIL — {len(failures)} check(s) failed: {', '.join(failures)}")
        sys.exit(1)
    print("PASS — queue, sessions, direction, retries and restart-safety all behave.")
