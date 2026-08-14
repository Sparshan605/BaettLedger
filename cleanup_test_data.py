"""
Removes all test-* session data from the real database, per Sparshan's request.
"""
import pyodbc
import json

with open("local.settings.json") as f:
    settings = json.load(f)

conn = pyodbc.connect(settings["Values"]["SQL_CONNECTION_STRING"], autocommit=True)
cur = conn.cursor()

cur.execute("DELETE FROM count_detection WHERE event_id IN (SELECT event_id FROM count_event WHERE session_id LIKE 'test-%')")
cur.execute("DELETE FROM count_event WHERE session_id LIKE 'test-%'")
cur.execute("DELETE FROM session WHERE session_id LIKE 'test-%'")

print("Test data cleaned up")
