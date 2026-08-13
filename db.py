"""
Database access for BaettLedger.
Connection string comes from the SQL_CONNECTION_STRING app setting
(itself a Key Vault reference — see azure-setup.md §3).
"""
import os
import pyodbc
from datetime import datetime, timezone

APPROVED_DEVICE_TYPES = {"cone", "sign", "barricade", "delineator"}


def get_connection():
    conn_str = os.environ["SQL_CONNECTION_STRING"]
    return pyodbc.connect(conn_str, autocommit=False)


def upsert_session(device_id, session_id, session_type, opened_at):
    """
    Returns (status, existing_row) where status is 'created' or 'exists'.
    api.md: POST /api/sessions -> 201 new, 200 if it already exists (same body).
    """
    session_date = opened_at.date()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT session_id, status FROM session WHERE session_id = ?", session_id)
        row = cur.fetchone()
        if row:
            return "exists", row
        cur.execute(
            """INSERT INTO session (session_id, device_id, session_type, session_date, opened_at, status)
               VALUES (?, ?, ?, ?, ?, 'open')""",
            session_id, device_id, session_type, session_date, opened_at,
        )
        conn.commit()
        return "created", None


def close_session(session_id, closed_at):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE session SET status = 'closed', closed_at = ? WHERE session_id = ?",
            closed_at, session_id,
        )
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM count_event WHERE session_id = ?", session_id)
        total_events = cur.fetchone()[0]
        return total_events


def insert_event(device_id, session_id, sequence, captured_at, photo_url):
    """
    The core write. Insert the row BEFORE Vision runs — device_type stays NULL.
    Idempotency is enforced by the DB unique constraint (device_id, session_id, sequence),
    NOT by an application-level check (api.md §4 — replays hit concurrent instances,
    a Python-level check loses that race).

    Returns (status, event_id) where status is 'created' or 'duplicate'.
    On 'duplicate', the existing row (and its original photo) is left untouched.
    """
    # Sanity-check captured_at vs server clock (api.md §5 — "two clocks").
    # Never reject the event over this; just note it for logs.
    now = datetime.now(timezone.utc)
    captured_naive = captured_at.replace(tzinfo=None) if captured_at.tzinfo else captured_at
    clock_skew_warning = abs((now.replace(tzinfo=None) - captured_naive).total_seconds()) > 86400

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO count_event (session_id, device_id, sequence, captured_at, photo_url)
                   VALUES (?, ?, ?, ?, ?)""",
                session_id, device_id, sequence, captured_at, photo_url,
            )
            conn.commit()
            cur.execute("SELECT @@IDENTITY")
            event_id = int(cur.fetchone()[0])
            return "created", event_id, clock_skew_warning
        except pyodbc.IntegrityError:
            # Duplicate-key hit -> return the EXISTING event_id. Never 409 (api.md §4):
            # Sparshan's uploader treats non-2xx as "retry later" and would loop forever.
            conn.rollback()
            cur.execute(
                "SELECT event_id FROM count_event WHERE device_id = ? AND session_id = ? AND sequence = ?",
                device_id, session_id, sequence,
            )
            row = cur.fetchone()
            return "duplicate", int(row[0]), clock_skew_warning


def update_event_analysis(event_id, device_type, count, confidence, needs_review, reason):
    """
    Called after Vision + Count Agent finish. Never called before the row exists.
    device_type must be in the approved closed set or 'unknown' — enforced by the
    caller (agent.py), not here, but we double check to protect the rollups.
    """
    if device_type is not None and device_type not in APPROVED_DEVICE_TYPES and device_type != "unknown":
        device_type = "unknown"
        needs_review = True

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE count_event
               SET device_type = ?, count = ?, confidence = ?, needs_review = ?, reason = ?
               WHERE event_id = ?""",
            device_type, count, confidence, 1 if needs_review else 0, reason, event_id,
        )
        conn.commit()


def confirm_event(event_id, device_type, count, confirmed_by="operator"):
    if device_type not in APPROVED_DEVICE_TYPES and device_type != "unknown":
        raise ValueError(f"device_type must be one of {APPROVED_DEVICE_TYPES | {'unknown'}}")
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE count_event
               SET device_type = ?, count = ?, needs_review = 0,
                   confirmed_by = ?, confirmed_at = ?
               WHERE event_id = ?""",
            device_type, count, confirmed_by, now, event_id,
        )
        conn.commit()
        return now


def get_today(date_str):
    """
    Powers GET /api/today. Uses the reconciliation query from api.md §5,
    plus raw event counts (Pi-authoritative, always correct even if Vision
    never ran) for the two big headline numbers.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # Sessions for the day
        cur.execute(
            """SELECT session_id, session_type, status FROM session
               WHERE session_date = ?""",
            date_str,
        )
        sessions = cur.fetchall()
        out_session = next(({"session_id": r[0], "status": r[2]} for r in sessions if r[1] == "OUT"), None)
        in_session = next(({"session_id": r[0], "status": r[2]} for r in sessions if r[1] == "IN"), None)

        # Headline numbers: raw event counts, ignoring device_type, per api.md §5.
        cur.execute(
            """SELECT COUNT(*) FROM count_event e JOIN session s ON s.session_id = e.session_id
               WHERE s.session_date = ? AND s.session_type = 'OUT'""",
            date_str,
        )
        starting_inventory = cur.fetchone()[0]

        cur.execute(
            """SELECT COUNT(*) FROM count_event e JOIN session s ON s.session_id = e.session_id
               WHERE s.session_date = ? AND s.session_type = 'IN'""",
            date_str,
        )
        ending_inventory = cur.fetchone()[0]

        # Per-type breakdown: the reconciliation query, verbatim from api.md §5.
        cur.execute(
            """
            SELECT
                COALESCE(o.device_type, i.device_type) AS device_type,
                COALESCE(o.total, 0) AS out_total,
                COALESCE(i.total, 0) AS in_total,
                COALESCE(o.total, 0) - COALESCE(i.total, 0) AS difference
            FROM
                (SELECT e.device_type, SUM(e.count) AS total
                 FROM count_event e JOIN session s ON s.session_id = e.session_id
                 WHERE s.session_date = ? AND s.session_type = 'OUT'
                 GROUP BY e.device_type) o
            FULL OUTER JOIN
                (SELECT e.device_type, SUM(e.count) AS total
                 FROM count_event e JOIN session s ON s.session_id = e.session_id
                 WHERE s.session_date = ? AND s.session_type = 'IN'
                 GROUP BY e.device_type) i
              ON o.device_type = i.device_type
            """,
            date_str, date_str,
        )
        by_type = [
            {"device_type": r[0] or "pending", "out_total": r[1], "in_total": r[2], "difference": r[3]}
            for r in cur.fetchall()
        ]

        cur.execute(
            """SELECT COUNT(*) FROM count_event e JOIN session s ON s.session_id = e.session_id
               WHERE s.session_date = ? AND e.device_type IS NULL""",
            date_str,
        )
        pending_analysis = cur.fetchone()[0]

        cur.execute(
            """SELECT MAX(e.received_at) FROM count_event e JOIN session s ON s.session_id = e.session_id
               WHERE s.session_date = ?""",
            date_str,
        )
        last_seen_row = cur.fetchone()
        device_last_seen = last_seen_row[0].isoformat() + "Z" if last_seen_row and last_seen_row[0] else None

        return {
            "date": date_str,
            "starting_inventory": starting_inventory,
            "ending_inventory": ending_inventory,
            "difference": starting_inventory - ending_inventory,
            "out_session": out_session,
            "in_session": in_session,
            "by_type": by_type,
            "device_last_seen": device_last_seen,
            "pending_analysis": pending_analysis,
        }


def get_events(session_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT event_id, sequence, device_type, count, confidence, needs_review,
                      reason, photo_url, captured_at, confirmed_at
               FROM count_event WHERE session_id = ? ORDER BY sequence""",
            session_id,
        )
        cols = ["event_id", "sequence", "device_type", "count", "confidence",
                "needs_review", "reason", "photo_url", "captured_at", "confirmed_at"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_review_queue():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT event_id, session_id, sequence, device_type, count, confidence,
                      reason, photo_url, captured_at
               FROM count_event
               WHERE needs_review = 1 AND confirmed_at IS NULL
               ORDER BY received_at"""
        )
        cols = ["event_id", "session_id", "sequence", "device_type", "count",
                "confidence", "reason", "photo_url", "captured_at"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
