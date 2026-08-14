"""
Run this once to (re)create the BaettLedger tables in the real Azure SQL
database. Uses the same SQL_CONNECTION_STRING you already have in
local.settings.json — no Azure Portal access needed, just the SQL
username/password Protsahan sent.

Usage:
    python run_schema.py
"""
import json
import re
import pyodbc

# Pull the connection string straight out of local.settings.json so you
# don't have to paste it twice.
with open("local.settings.json") as f:
    settings = json.load(f)
CONN_STR = settings["Values"]["SQL_CONNECTION_STRING"]

DROP_STATEMENTS = """
IF OBJECT_ID('count_detection', 'U') IS NOT NULL DROP TABLE count_detection;
IF OBJECT_ID('count_event', 'U') IS NOT NULL DROP TABLE count_event;
IF OBJECT_ID('daily_total', 'U') IS NOT NULL DROP TABLE daily_total;
IF OBJECT_ID('session', 'U') IS NOT NULL DROP TABLE session;
"""

def run_schema():
    with open("schema.sql") as f:
        schema_sql = f.read()

    # Strip comment-only lines so they don't confuse the batch splitter below.
    statements = re.split(r";\s*\n", schema_sql)

    conn = pyodbc.connect(CONN_STR, autocommit=True)
    cur = conn.cursor()

    print("Dropping old tables if they exist...")
    for stmt in DROP_STATEMENTS.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    print("  done.")

    print("Creating tables from schema.sql...")
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue
        # A chunk can legitimately start with an explanatory "--" comment
        # line and still contain real SQL further down (e.g. a comment
        # directly above a CREATE TABLE). Only skip chunks that are
        # ENTIRELY comments/blank lines with no actual statement in them.
        real_lines = [ln for ln in stmt.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        if not real_lines:
            continue
        try:
            cur.execute(stmt)
        except pyodbc.Error as e:
            print(f"  ERROR on statement:\n{stmt[:200]}\n  -> {e}")
            raise
    print("  done.")

    print("\nVerifying tables now in the database:")
    cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
    for row in cur.fetchall():
        print(f"  - {row[0]}")

    conn.close()
    print("\nSchema applied successfully.")


if __name__ == "__main__":
    run_schema()
