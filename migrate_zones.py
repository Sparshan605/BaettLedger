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

Connection string: local.settings.json if present, otherwise .env. Driver:
pyodbc if installed, otherwise pure-Python pytds (`pip install python-tds
"pyOpenSSL<25"`), because a Mac with no ODBC driver is the normal case here and
a migration you cannot run is not a migration.

If it hangs and then times out, it is almost certainly the Azure SQL firewall
rather than anything in this script. TCP 1433 accepts the connection at the
gateway and the login is what gets dropped, so it looks like a hang, not a
refusal. Check that your current public IP has a rule:

    az sql server firewall-rule list --server sql-baettledger16 -g rg-baettledger -o table
"""
import json
import os
import re
import sys

ALLOWED = ("wide", "closeup", "left", "middle", "right", "overview")
CONSTRAINT_NAME = "ck_event_zone"

# No bound parameters anywhere below. pyodbc wants '?' and pytds wants '%s', and
# every value here is a module constant rather than input, so sidestepping
# parameters entirely is what lets one script run under either driver.
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

DEFINITION_OF_NEW = f"""
SELECT definition FROM sys.check_constraints WHERE name = '{CONSTRAINT_NAME}'
"""


def connection_string():
    """local.settings.json first — same source run_schema.py uses — then .env."""
    settings = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local.settings.json")
    if os.path.exists(settings):
        with open(settings) as f:
            value = json.load(f)["Values"].get("SQL_CONNECTION_STRING")
        if value:
            return value, "local.settings.json"

    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        with open(env) as f:
            # .env here is a mix of JSON-ish `"KEY": "value",` lines and plain
            # `KEY=value` ones, so match either rather than assuming a format.
            match = re.search(
                r'SQL_CONNECTION_STRING["\']?\s*[:=]\s*["\']([^"\']+)["\']', f.read()
            )
        if match:
            return match.group(1), ".env"

    raise SystemExit(
        "No SQL_CONNECTION_STRING found in local.settings.json or .env.\n"
        "Copy local.settings.json.example and fill it in."
    )


def parse_odbc(conn_str):
    """ODBC keyword string -> dict, lowercased keys. Only pytds needs this."""
    out = {}
    for part in conn_str.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip().lower()] = value.strip()
    return out


def connect(conn_str):
    """Return (connection, driver_name). pyodbc when available, else pytds."""
    try:
        import pyodbc
    except ImportError:
        pass
    else:
        return pyodbc.connect(conn_str, autocommit=True), "pyodbc"

    try:
        import ssl

        import pytds
    except ImportError:
        raise SystemExit(
            "Neither pyodbc nor pytds is installed. Either install the Microsoft\n"
            "ODBC driver plus pyodbc, or the pure-Python client:\n"
            '    pip install python-tds "pyOpenSSL<25"\n'
            "(pyOpenSSL 25+ removed an API pytds still calls, hence the pin.)"
        )

    kv = parse_odbc(conn_str)
    server = kv.get("server", "").replace("tcp:", "")
    host, _, port = server.partition(",")
    return (
        pytds.connect(
            dsn=host,
            port=int(port) if port else 1433,
            database=kv.get("database"),
            user=kv.get("uid") or kv.get("user id"),
            password=kv.get("pwd") or kv.get("password"),
            cafile=ssl.get_default_verify_paths().openssl_cafile,
            validate_host=True,
            autocommit=True,
            login_timeout=30,
        ),
        "pytds",
    )


def migrate():
    conn_str, source = connection_string()
    conn, driver = connect(conn_str)
    print(f"connected via {driver}, credentials from {source}\n")
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
        cur.execute(DEFINITION_OF_NEW)
        definition = cur.fetchone()[0]
        if all(f"'{z}'" in definition for z in ALLOWED):
            print("already migrated — nothing to do.")
            conn.close()
            return

    for name in existing:
        # From sys.check_constraints, not from input — but it is an identifier
        # rather than a value, so it could not be a bound parameter regardless.
        print(f"  dropping {name} ...")
        cur.execute(f"ALTER TABLE count_event DROP CONSTRAINT [{name}]")

    print(f"  adding {CONSTRAINT_NAME} ({', '.join(ALLOWED)}) ...")
    # WITH CHECK validates the rows already in the table. Every existing zone is
    # in ALLOWED, so this passes; if it ever fails, something wrote a zone that
    # no version of the code permits and that is worth stopping for.
    cur.execute(ADD_NEW)

    cur.execute(DEFINITION_OF_NEW)
    print(f"\nnow: {cur.fetchone()[0]}")

    # Prove the thing this migration exists for actually works, then undo it. A
    # migration that reports success without exercising the new value is how you
    # find out at the demo. INSERT..SELECT so there are still no parameters.
    cur.execute("SELECT COUNT(*) FROM session")
    if cur.fetchone()[0]:
        try:
            cur.execute(
                """INSERT INTO count_event (session_id, device_id, sequence, zone, captured_at)
                   SELECT TOP 1 session_id, device_id, -999, 'wide', SYSUTCDATETIME()
                   FROM session ORDER BY opened_at DESC"""
            )
            cur.execute("DELETE FROM count_event WHERE sequence = -999")
            print("verified: a 'wide' row inserts and was cleaned up again.")
        except Exception as e:
            print(f"FAILED to insert a 'wide' row after migrating: {e}")
            conn.close()
            raise
    else:
        print("no sessions yet, so the insert check was skipped.")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    try:
        migrate()
    except SystemExit:
        raise
    except Exception as e:
        print(f"\nMigration FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
