"""
Database access for BaettLedger — v2, zone-based architecture.
Connection string comes from the SQL_CONNECTION_STRING app setting
(itself a Key Vault reference — see azure-setup.md §3).

The beam sensor is gone. A session now produces two photos of one capture:
`wide` (the whole load, uncropped — this is the count) and `closeup` (the same
load through a tighter frame — an independent second opinion, never added to
the total). Each photo can show several device types at once, stored as one
count_detection row per type. See docs/api.md §1-2 for the full rationale
before touching this file.

This replaced a left/middle/right/overview split on Aug 13. Rows from that
design are still in the table and still total correctly — see COUNT_ZONES.
"""
import os
import pyodbc
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

APPROVED_DEVICE_TYPES = {"cone", "sign", "barricade", "delineator", "barrel"}

# The day a session belongs to, as the crew sees it.
#
# Timestamps stay UTC everywhere; only the DAY is local. UTC is the wrong
# boundary for a crew in Vancouver because it rolls at 5 PM local — mid-way
# through the evening return trip — which filed a single OUT/IN run under two
# different dates and left the dashboard with an OUT it could never pair.
#
# The Pi derives the same day from its own clock settings (edge/store.py). The
# server has no local timezone to read — Azure Functions run in UTC — so the
# site's zone is named here, overridable with an OPERATING_TZ app setting if the
# device ever moves. Both ends must agree or the reconciliation splits again.
OPERATING_TZ = ZoneInfo(os.environ.get("OPERATING_TZ", "America/Vancouver"))


def operating_date(dt):
    """The operating day a timestamp falls in. Naive input is read as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(OPERATING_TZ).date()


def today_str():
    """Today (YYYY-MM-DD) at the site, not in UTC."""
    return operating_date(datetime.now(timezone.utc)).isoformat()

# An inventory is two photos: `wide` is the uncropped frame and carries the
# count, `closeup` is the same load through a tighter frame and is only ever a
# second opinion. left/middle/right/overview are the retired three-zone design;
# they stay approved so the sessions already in the database keep working and an
# un-updated Pi is not rejected mid-demo.
COUNT_ZONES = {"wide", "left", "middle", "right"}
CHECK_ZONES = {"closeup", "overview"}
APPROVED_ZONES = COUNT_ZONES | CHECK_ZONES

# Interpolated into SQL below. Safe — these are module constants, never input —
# and having them in one place is what stops the two halves of a reconciliation
# query drifting apart, which is exactly how the overview once leaked into a
# total and doubled every number on the dashboard.
_COUNTED_SQL = "e.zone NOT IN ('closeup','overview')"
_CHECK_SQL = "e.zone IN ('closeup','overview')"

ZONE_OVERVIEW_DIFF_THRESHOLD = 2  # api.md §6a


def get_connection():
    conn_str = os.environ["SQL_CONNECTION_STRING"]
    return pyodbc.connect(conn_str, autocommit=False)


def upsert_session(device_id, session_id, session_type, opened_at):
    """
    Returns (status, existing_row) where status is 'created' or 'exists'.
    api.md: POST /api/sessions -> 201 new, 200 if it already exists (same body).
    """
    # Not opened_at.date(): that is the UTC day, and it disagrees with the day
    # the Pi filed the session under for every capture after 5 PM local.
    session_date = operating_date(opened_at)
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
    Sums count_detection per device_type for the counted photo(s) versus the
    cross-check photo alone, for one session. Used by the cross-check
    (api.md §6a) once every capture in the session has been analyzed.

    Today that is `wide` against `closeup`; for sessions captured under the old
    design it is left+middle+right against `overview`. Both are handled by the
    same query, which is why the zone lists live in one constant.

    Returns (zone_totals, overview_totals, event_ids, all_analyzed) where
    event_ids is {"counted": [id, ...], "check": int|None}.
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
            f"""SELECT d.device_type, SUM(d.count)
               FROM count_detection d JOIN count_event e ON e.event_id = d.event_id
               WHERE e.session_id = ? AND {_COUNTED_SQL}
               GROUP BY d.device_type""",
            session_id,
        )
        zone_totals = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            f"""SELECT e.event_id, d.device_type, SUM(d.count)
               FROM count_detection d JOIN count_event e ON e.event_id = d.event_id
               WHERE e.session_id = ? AND {_CHECK_SQL}
               GROUP BY e.event_id, d.device_type""",
            session_id,
        )
        overview_rows = cur.fetchall()
        overview_totals = {row[1]: row[2] for row in overview_rows}

        # Every counted photo in the session, whether or not it has detections —
        # a zone that came back empty is still a row a human may need to correct.
        cur.execute(
            f"SELECT e.event_id FROM count_event e WHERE e.session_id = ? AND {_COUNTED_SQL}"
            " ORDER BY e.sequence",
            session_id,
        )
        event_ids = {
            "counted": [row[0] for row in cur.fetchall()],
            "check": overview_rows[0][0] if overview_rows else None,
        }

        return zone_totals, overview_totals, event_ids, all_analyzed


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
    No-ops until every capture in the session has been analyzed. Flags the
    cross-check event (never the counted one) when the two totals disagree by
    more than ZONE_OVERVIEW_DIFF_THRESHOLD for any device type.

    Does NOT auto-correct anything — it only flags for a human to look. The
    close-up is a sanity check, not a better measurement: it sees a tighter
    frame, so when they differ the wide shot is still the one that counted
    everything.
    """
    zone_totals, overview_totals, event_ids, all_analyzed = get_session_zone_totals(session_id)
    if not all_analyzed or event_ids["check"] is None:
        return

    all_types = set(zone_totals) | set(overview_totals)
    mismatches = []
    for device_type in sorted(all_types):
        z = zone_totals.get(device_type, 0)
        o = overview_totals.get(device_type, 0)
        if abs(z - o) > ZONE_OVERVIEW_DIFF_THRESHOLD:
            mismatches.append(f"counted {z} {device_type}, cross-check shows {o}")

    if not mismatches:
        return

    # Flag the COUNTED photo, not the cross-check one.
    #
    # The old design flagged the overview, which was defensible when the
    # overview was the odd one out among four rows. With two photos it is
    # actively wrong: the operator taps the amber row, corrects the numbers, and
    # the headline total does not move — because the row they just fixed is the
    # one that was never in the total. The number on screen stays wrong and the
    # human check appears to do nothing, which is the worst possible thing to
    # demonstrate. Blame the row whose correction actually fixes the total.
    #
    # A legacy session has three counted rows and no way to tell which is at
    # fault, so those keep flagging the overview as before.
    counted = event_ids["counted"]
    target = counted[0] if len(counted) == 1 else event_ids["check"]
    flag_overview_mismatch(target, "; ".join(mismatches))


def get_today(date_str):
    """
    Powers GET /api/today. Headline numbers come from the counted photo per
    api.md §2 — the cross-check photo is excluded everywhere, because it shows
    the same devices and would roughly double every number (api.md §5).
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # The day's most recent OUT and most recent IN — a matched pair.
        #
        # This used to sum every session of the day. In real operation that is
        # the same thing, because a day has one morning load and one evening
        # return. In practice it meant every rehearsal accumulated: five test
        # captures made "starting inventory" the sum of all five, and a stale
        # OUT from hours earlier was reconciled against a fresh IN.
        #
        # Comparing the latest pair makes a re-run replace the previous one
        # instead of adding to it, so you can rehearse repeatedly and always
        # see just this run. The tradeoff: if a crew genuinely ran two separate
        # OUT loads in one day, only the later one counts.
        cur.execute(
            """SELECT session_id, session_type, status FROM session
               WHERE session_date = ?
               ORDER BY opened_at DESC""",
            date_str,
        )
        sessions = cur.fetchall()
        out_session = next(({"session_id": r[0], "status": r[2]} for r in sessions if r[1] == "OUT"), None)
        in_session = next(({"session_id": r[0], "status": r[2]} for r in sessions if r[1] == "IN"), None)

        # NULL is fine — the FULL OUTER JOIN below simply finds no rows on that
        # side, which is exactly right before the first inventory of the day.
        out_id = out_session["session_id"] if out_session else None
        in_id = in_session["session_id"] if in_session else None

        # Reconciliation query, from api.md §5 — count_detection joined through
        # count_event, the cross-check photo excluded from BOTH halves. Leave it
        # in one half and the day's difference is pure fiction.
        cur.execute(
            f"""
            SELECT
                COALESCE(o.device_type, i.device_type) AS device_type,
                COALESCE(o.total, 0) AS out_total,
                COALESCE(i.total, 0) AS in_total,
                COALESCE(o.total, 0) - COALESCE(i.total, 0) AS difference
            FROM
                (SELECT d.device_type, SUM(d.count) AS total
                 FROM count_detection d
                 JOIN count_event e ON e.event_id = d.event_id
                 WHERE e.session_id = ?
                   AND {_COUNTED_SQL}
                 GROUP BY d.device_type) o
            FULL OUTER JOIN
                (SELECT d.device_type, SUM(d.count) AS total
                 FROM count_detection d
                 JOIN count_event e ON e.event_id = d.event_id
                 WHERE e.session_id = ?
                   AND {_COUNTED_SQL}
                 GROUP BY d.device_type) i
              ON o.device_type = i.device_type
            """,
            out_id, in_id,
        )
        by_type = [
            {"device_type": r[0] or "pending", "out_total": r[1], "in_total": r[2], "difference": r[3]}
            for r in cur.fetchall()
        ]

        starting_inventory = sum(r["out_total"] for r in by_type)
        ending_inventory = sum(r["in_total"] for r in by_type)

        # Scoped to the same pair as the totals. Counting the whole day would
        # mark the screen "still analyzing" because of an old test capture that
        # has nothing to do with the run being shown.
        cur.execute(
            """SELECT COUNT(*) FROM count_event e
               WHERE e.session_id IN (?, ?) AND e.analyzed_at IS NULL""",
            out_id, in_id,
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
