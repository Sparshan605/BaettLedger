"""
Widen the count_detection.device_type CHECK constraint to allow 'barrel'.

RUN THIS BEFORE DEPLOYING THE NEW agent.py. Until it has run, the live table
only permits cone/sign/barricade/delineator/unknown, and the first photo where
the agent names a barrel is rejected by the database — save_detections raises
mid-insert, the event keeps analyzed_at NULL and the dashboard shows it as
pending forever.

Why 'barrel' at all: the loads carry drum/channelizer barrels, and every one of
them was coming back as `unknown` with needs_review set, because unknown is the
only bucket the old list had for them. That is not a vision problem to tune —
the type simply did not exist.

Like migrate_zones.py this touches NO data and drops NO tables. It swaps one
constraint for a wider one; every existing value stays permitted, so the rows
already in the table remain valid. Safe to run twice.

Usage:
    python migrate_devices.py

Connection string and driver handling are migrate_zones.py's — imported rather
than copied, so there is one place where the pyodbc/pytds fallback lives.
"""
from migrate_zones import connect, connection_string

ALLOWED = ("cone", "sign", "barricade", "delineator", "barrel", "unknown")
CONSTRAINT_NAME = "ck_detection_device_type"

# No bound parameters anywhere below — same reason as migrate_zones.py: pyodbc
# wants '?' and pytds wants '%s', and every value here is a module constant.
FIND_OLD = """
SELECT cc.name
FROM sys.check_constraints cc
WHERE cc.parent_object_id = OBJECT_ID('count_detection')
  AND cc.definition LIKE '%device_type%'
"""

ADD_NEW = f"""
ALTER TABLE count_detection WITH CHECK ADD CONSTRAINT {CONSTRAINT_NAME}
    CHECK (device_type IN ({','.join(f"'{d}'" for d in ALLOWED)}))
"""

DEFINITION_OF_NEW = f"""
SELECT definition FROM sys.check_constraints WHERE name = '{CONSTRAINT_NAME}'
"""


def migrate():
    conn_str, source = connection_string()
    conn, driver = connect(conn_str)
    print(f"connected via {driver}, credentials from {source}\n")
    cur = conn.cursor()

    cur.execute(
        "SELECT device_type, COUNT(*), SUM(count) FROM count_detection "
        "GROUP BY device_type ORDER BY device_type"
    )
    before = cur.fetchall()
    print("device types currently in count_detection:")
    for device_type, rows, total in before:
        print(f"  {device_type:<12} {rows:>4} row(s), {total} device(s)")
    if not before:
        print("  (none — the table is empty)")

    cur.execute(FIND_OLD)
    existing = [row[0] for row in cur.fetchall()]
    print(f"\ndevice_type CHECK constraint(s) found: {existing or '(none)'}")

    if existing == [CONSTRAINT_NAME]:
        cur.execute(DEFINITION_OF_NEW)
        definition = cur.fetchone()[0]
        if all(f"'{d}'" in definition for d in ALLOWED):
            print("already migrated — nothing to do.")
            conn.close()
            return

    for name in existing:
        print(f"  dropping {name} ...")
        cur.execute(f"ALTER TABLE count_detection DROP CONSTRAINT [{name}]")

    print(f"  adding {CONSTRAINT_NAME} ({', '.join(ALLOWED)}) ...")
    cur.execute(ADD_NEW)

    cur.execute(DEFINITION_OF_NEW)
    print(f"\nnow: {cur.fetchone()[0]}")

    # Prove a 'barrel' row actually inserts, then take it back out. uq_detection
    # is (event_id, device_type), so borrowing a real event is safe only if that
    # event has no barrel row yet — hence the NOT EXISTS.
    cur.execute("SELECT COUNT(*) FROM count_event")
    if cur.fetchone()[0]:
        try:
            cur.execute(
                """INSERT INTO count_detection (event_id, device_type, count)
                   SELECT TOP 1 e.event_id, 'barrel', -999
                   FROM count_event e
                   WHERE NOT EXISTS (SELECT 1 FROM count_detection d
                                     WHERE d.event_id = e.event_id
                                       AND d.device_type = 'barrel')
                   ORDER BY e.event_id DESC"""
            )
            cur.execute("DELETE FROM count_detection WHERE count = -999")
            print("verified: a 'barrel' row inserts and was cleaned up again.")
        except Exception as e:
            print(f"FAILED to insert a 'barrel' row after migrating: {e}")
            conn.close()
            raise
    else:
        print("no events yet, so the insert check was skipped.")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    migrate()
