"""
Widen the count_event.zone CHECK constraint to allow 'wide' and 'closeup'.

RUN THIS BEFORE PUTTING THE TWO-PHOTO PI CODE ON THE PI. Until it has run, the
live table only permits left/middle/right/overview, and the first `wide` photo
the Pi uploads is rejected by the database — /api/events answers 500, the
uploader treats that as "retry later", and the queue backs up behind a request
that can never succeed. Nothing is lost, but nothing reaches the dashboard
either, which is a bad thing to discover in front of an audience.

Unlike run_schema.py this touches NO data and drops NO tables. It swaps one
constraint for a wider one. The old zone names stay permitted so the rehearsal
sessions already in the database remain valid.

Safe to run twice — the second run finds the constraint already correct and
does nothing.

Usage:
    python migrate_zones.py
"""
import json

import pyodbc

# Same source as run_schema.py, so there is one place to keep the credentials.
with open("local.settings.json") as f:
    CONN_STR = json.load(f)["Values"]["SQL_CONNECTION_STRING"]

ALLOWED = ("wide", "closeup", "left", "middle", "right", "overview")
CONSTRAINT_NAME = "ck_event_zone"

# The original constraint was declared inline on the column and therefore got an
# auto-generated name (CK__count_ev__zone__A1B2C3D4), which differs per
# database — it cannot be dropped by a name written here. Find it by what it
# constrains instead.
FIND_OLD = """
SELECT cc.name
FROM sys.check_constraints cc
WHERE cc.parent_object_id = OBJECT_ID('count_event')
  AND cc.definition LIKE '%zone%'
"""

ADD_NEW = f"""
ALTER TABLE count_event WITH CHECK ADD CONSTRAINT {CONSTRAINT_NAME}
    CHECK (zone IN ({','.join(f"'{z}'" for z in ALLOWED)}))
"""


def migrate():
    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cur = conn.cursor()

    cur.execute("SELECT zone, COUNT(*) FROM count_event GROUP BY zone ORDER BY zone")
    before = cur.fetchall()
    print("zones currently in count_event:")
    for zone, n in before:
        print(f"  {zone:<10} {n:>4} row(s)")
    if not before:
        print("  (none — the table is empty)")

    cur.execute(FIND_OLD)
    existing = [row[0] for row in cur.fetchall()]
    print(f"\nzone CHECK constraint(s) found: {existing or '(none)'}")

    if existing == [CONSTRAINT_NAME]:
        cur.execute(
            "SELECT definition FROM sys.check_constraints WHERE name = ?", CONSTRAINT_NAME
        )
        definition = cur.fetchone()[0]
        if all(f"'{z}'" in definition for z in ALLOWED):
            print("already migrated — nothing to do.")
            conn.close()
            return

    for name in existing:
        # The name comes from sys.check_constraints, not from input, but it is
        # still an identifier rather than a value, so it cannot be a parameter.
        print(f"  dropping {name} ...")
        cur.execute(f"ALTER TABLE count_event DROP CONSTRAINT [{name}]")

    print(f"  adding {CONSTRAINT_NAME} ({', '.join(ALLOWED)}) ...")
    # WITH CHECK validates the rows already in the table. Every existing zone is
    # in ALLOWED, so this passes; if it ever fails, something wrote a zone that
    # no version of the code permits and that is worth stopping for.
    cur.execute(ADD_NEW)

    cur.execute(
        "SELECT definition FROM sys.check_constraints WHERE name = ?", CONSTRAINT_NAME
    )
    print(f"\nnow: {cur.fetchone()[0]}")

    # Prove the thing this migration exists for actually works, then undo it.
    # A migration that reports success without exercising the new value is how
    # you find out at the demo.
    cur.execute("SELECT TOP 1 session_id, device_id FROM session ORDER BY opened_at DESC")
    sample = cur.fetchone()
    if sample:
        try:
            cur.execute(
                """INSERT INTO count_event (session_id, device_id, sequence, zone, captured_at)
                   VALUES (?, ?, -999, 'wide', SYSUTCDATETIME())""",
                sample[0], sample[1],
            )
            cur.execute("DELETE FROM count_event WHERE sequence = -999")
            print("verified: a 'wide' row inserts and was cleaned up again.")
        except pyodbc.Error as e:
            print(f"FAILED to insert a 'wide' row after migrating: {e}")
            conn.close()
            raise
    else:
        print("no sessions yet, so the insert check was skipped.")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
