"""
Database access for BaettLedger — v2, zone-based architecture.
Connection string comes from the SQL_CONNECTION_STRING app setting
(itself a Key Vault reference — see azure-setup.md §3).

The beam sensor is gone. A session now produces four photos (left, middle,
right, overview); each photo can show several device types at once, stored
as one count_detection row per type. See docs/api.md §1-2 for the full
rationale before touching this file.
"""
import os
import pyodbc
from datetime import datetime, timezone

APPROVED_DEVICE_TYPES = {"cone", "sign", "barricade", "delineator"}
APPROVED_ZONES = {"left", "middle", "right", "overview"}
ZONE_OVERVIEW_DIFF_THRESHOLD = 2  # api.md §6a


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


def insert_event(device_id, session_id, sequence, zone, captured_at, photo_url):
    """
    The core write. Insert the row BEFORE Vision/Agent run — analyzed_at stays
    NULL. Idempotency is enforced by the DB unique constraint (device_id,
    session_id, sequence), NOT by an application-level check (api.md §4 —
    replays hit concurrent instances, a Python-level check loses that race).

    zone must already be validated by the caller (api.md §3: an invalid zone
    is a 400, not silently absorbed here) — this function trusts it.

    Returns (status, event_id, clock_skew_warning) where status is
    'created' or 'duplicate'.
    """
    now = datetime.now(timezone.utc)
    captured_naive = captured_at.replace(tzinfo=None) if captured_at.tzinfo else captured_at
    clock_skew_warning = abs((now.replace(tzinfo=None) - captured_naive).total_seconds()) > 86400

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO count_event (session_id, device_id, sequence, zone, captured_at, photo_url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                session_id, device_id, sequence, zone, captured_at, photo_url,
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


def save_detections(event_id, devices, confidence, needs_review, reason):
    """
    Called after Vision + Count Agent finish for one photo. `devices` is a
    list of {"device_type", "count"} dicts (possibly empty — an empty zone
    is a real, analyzed state, not a pending one, api.md §1 rule 2).

    On re-analysis, delete this event's old detections and reinsert — never
    accumulate, or a retry doubles the zone (api.md §6).
    """
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM count_detection WHERE event_id = ?", event_id)
        for d in devices:
            device_type = d.get("device_type")
            if device_type not in APPROVED_DEVICE_TYPES and device_type != "unknown":
                device_type = "unknown"
                needs_review = True
            cur.execute(
                "INSERT INTO count_detection (event_id, device_type, count) VALUES (?, ?, ?)",
                event_id, device_type, int(d.get("count", 0)),
            )
        cur.execute(
            """UPDATE count_event
               SET analyzed_at = ?, confidence = ?, needs_review = ?, reason = ?
               WHERE event_id = ?""",
            now, confidence, 1 if needs_review else 0, reason, event_id,
        )
        conn.commit()


def confirm_event(event_id, devices, confirmed_by="operator"):
    """
    api.md/dashboard.md: POST /api/events/{id}/confirm replaces the WHOLE
    devices list for that event. Sending an empty list zeroes the zone.
    """
    for d in devices:
        dt = d.get("device_type")
        if dt not in APPROVED_DEVICE_TYPES and dt != "unknown":
            raise ValueError(f"device_type must be one of {APPROVED_DEVICE_TYPES | {'unknown'}}")

    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM count_detection WHERE event_id = ?", event_id)
        for d in devices:
            cur.execute(
                "INSERT INTO count_detection (event_id, device_type, count) VALUES (?, ?, ?)",
                event_id, d["device_type"], int(d["count"]),
            )
        cur.execute(
            """UPDATE count_event
               SET needs_review = 0, confirmed_by = ?, confirmed_at = ?
               WHERE event_id = ?""",
            confirmed_by, now, event_id,
        )
        conn.commit()
        return now


def get_session_zone_totals(session_id):
    """
    Sums count_detection per device_type for the three real zones (excludes
    overview) versus the overview photo alone, for one session. Used by the
    zone/overview cross-check (api.md §6a) once all four captures are analyzed.

    Returns (zone_totals: {device_type: count}, overview_totals: {device_type: count},
             overview_event_id: int|None, all_analyzed: bool)
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*), SUM(CASE WHEN analyzed_at IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM count_event WHERE session_id = ?",
            session_id,
        )
        total_rows, analyzed_rows = cur.fetchone()
        all_analyzed = total_rows > 0 and total_rows == (analyzed_rows or 0)

        cur.execute(
            """SELECT d.device_type, SUM(d.count)
               FROM count_detection d JOIN count_event e ON e.event_id = d.event_id
               WHERE e.session_id = ? AND e.zone <> 'overview'
               GROUP BY d.device_type""",
            session_id,
        )
        zone_totals = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            """SELECT e.event_id, d.device_type, SUM(d.count)
               FROM count_detection d JOIN count_event e ON e.event_id = d.event_id
               WHERE e.session_id = ? AND e.zone = 'overview'
               GROUP BY e.event_id, d.device_type""",
            session_id,
        )
        overview_rows = cur.fetchall()
        overview_totals = {row[1]: row[2] for row in overview_rows}
        overview_event_id = overview_rows[0][0] if overview_rows else None

        return zone_totals, overview_totals, overview_event_id, all_analyzed


def flag_overview_mismatch(event_id, reason):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE count_event SET needs_review = 1, reason = ? WHERE event_id = ?",
            reason, event_id,
        )
        conn.commit()


def run_zone_overview_cross_check(session_id):
    """
    api.md §6a. Call this after saving detections for any event in a session.
    No-ops until all four captures in the session have been analyzed. Flags
    the overview event (not the zones) when zone_total and overview_total
    disagree by more than ZONE_OVERVIEW_DIFF_THRESHOLD for any device type.
    Does NOT auto-correct anything — it only flags for a human to look.
    """
    zone_totals, overview_totals, overview_event_id, all_analyzed = get_session_zone_totals(session_id)
    if not all_analyzed or overview_event_id is None:
        return

    all_types = set(zone_totals) | set(overview_totals)
    mismatches = []
    for device_type in sorted(all_types):
        z = zone_totals.get(device_type, 0)
        o = overview_totals.get(device_type, 0)
        if abs(z - o) > ZONE_OVERVIEW_DIFF_THRESHOLD:
            mismatches.append(f"zones total {z} {device_type}, overview shows {o}")

    if mismatches:
        flag_overview_mismatch(overview_event_id, "; ".join(mismatches))


def get_today(date_str):
    """
    Powers GET /api/today. Headline numbers are the three zones summed per
    api.md §2 — the overview is excluded everywhere (it would roughly double
    every number, api.md §5).
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # Newest first. Without the ORDER BY, next() below picked whichever row
        # SQL happened to return first — in practice the oldest — so re-running
        # an inventory left the dashboard's Photos screen showing the first
        # capture of the day while the totals already included the newest one.
        #
        # The totals themselves are unaffected: the reconciliation below sums
        # every session of the day. This only chooses which session the Photos
        # screen links to, and that should be the most recent.
        cur.execute(
            """SELECT session_id, session_type, status FROM session
               WHERE session_date = ?
               ORDER BY opened_at DESC""",
            date_str,
        )
        sessions = cur.fetchall()
        out_session = next(({"session_id": r[0], "status": r[2]} for r in sessions if r[1] == "OUT"), None)
        in_session = next(({"session_id": r[0], "status": r[2]} for r in sessions if r[1] == "IN"), None)

        # Reconciliation query, verbatim from api.md §5 — count_detection joined
        # through count_event, overview excluded from both halves.
        cur.execute(
            """
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
                 WHERE s.session_date = ? AND s.session_type = 'OUT'
                   AND e.zone <> 'overview'
                 GROUP BY d.device_type) o
            FULL OUTER JOIN
                (SELECT d.device_type, SUM(d.count) AS total
                 FROM count_detection d
                 JOIN count_event e ON e.event_id = d.event_id
                 JOIN session s     ON s.session_id = e.session_id
                 WHERE s.session_date = ? AND s.session_type = 'IN'
                   AND e.zone <> 'overview'
                 GROUP BY d.device_type) i
              ON o.device_type = i.device_type
            """,
            date_str, date_str,
        )
        by_type = [
            {"device_type": r[0] or "pending", "out_total": r[1], "in_total": r[2], "difference": r[3]}
            for r in cur.fetchall()
        ]

        starting_inventory = sum(r["out_total"] for r in by_type)
        ending_inventory = sum(r["in_total"] for r in by_type)

        cur.execute(
            """SELECT COUNT(*) FROM count_event e JOIN session s ON s.session_id = e.session_id
               WHERE s.session_date = ? AND e.analyzed_at IS NULL""",
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
    """
    One entry per photo (up to 4 per session), each carrying its own
    `devices` list — dashboard.md §3 shape.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT event_id, sequence, zone, confidence, needs_review,
                      reason, photo_url, captured_at, analyzed_at, confirmed_at
               FROM count_event WHERE session_id = ? ORDER BY sequence""",
            session_id,
        )
        cols = ["event_id", "sequence", "zone", "confidence", "needs_review",
                "reason", "photo_url", "captured_at", "analyzed_at", "confirmed_at"]
        events = [dict(zip(cols, row)) for row in cur.fetchall()]

        for ev in events:
            cur.execute(
                "SELECT device_type, count FROM count_detection WHERE event_id = ?",
                ev["event_id"],
            )
            ev["devices"] = [{"device_type": r[0], "count": r[1]} for r in cur.fetchall()]

        return events


def get_review_queue():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT event_id, session_id, sequence, zone, confidence,
                      reason, photo_url, captured_at
               FROM count_event
               WHERE needs_review = 1 AND confirmed_at IS NULL
               ORDER BY received_at"""
        )
        cols = ["event_id", "session_id", "sequence", "zone", "confidence",
                "reason", "photo_url", "captured_at"]
        events = [dict(zip(cols, row)) for row in cur.fetchall()]

        for ev in events:
            cur.execute(
                "SELECT device_type, count FROM count_detection WHERE event_id = ?",
                ev["event_id"],
            )
            ev["devices"] = [{"device_type": r[0], "count": r[1]} for r in cur.fetchall()]

        return events
