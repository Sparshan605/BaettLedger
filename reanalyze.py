"""
Re-run Vision + the Count Agent over photos that are already in the database.

Why this exists: replaying a photo through POST /api/events does NOT re-analyse
it. The idempotency key (device_id, session_id, sequence) makes the second POST
a duplicate, and the duplicate path returns 200 immediately without touching
Vision or the agent (api.md §4). That is correct for the Pi — a retry after a
lost acknowledgement must never double-count — but it means a prompt change or a
model change leaves every existing session frozen at its old numbers.

That happened on Aug 14: the Count Agent was only ever shown Azure AI Vision's
JSON, which does not detect traffic cones, so real loads came back as "1 sign".
The agent now reads the JPEG itself, and the sessions captured before that still
needed correcting.

This writes through db.save_detections() and db.run_zone_overview_cross_check() —
the same functions the API uses — so re-analysis and first analysis cannot drift.

Usage:
    python reanalyze.py                     # today's OUT and IN sessions
    python reanalyze.py 2026-08-14          # that date's OUT and IN sessions
    python reanalyze.py sess-2026-08-14-061219 [more...]
    python reanalyze.py --dry-run 2026-08-14

Needs the same connection string and keys as the Function App (local.settings.json
or .env), and either pyodbc or pytds — see migrate_zones.py for the driver notes.
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://func-baettledger.azurewebsites.net"
REPO = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Populate os.environ from local.settings.json or .env, whichever exists.

    .env here is a mix of JSON-ish `"KEY": "value",` lines and plain KEY=value,
    and at least one value arrived URL-encoded (FOUNDRY_ENDPOINT carried a
    trailing %22 that turns every model call into a 404), so unquote and strip.
    """
    settings = os.path.join(REPO, "local.settings.json")
    if os.path.exists(settings):
        with open(settings) as f:
            for k, v in json.load(f)["Values"].items():
                os.environ.setdefault(k, v)

    env = os.path.join(REPO, ".env")
    if os.path.exists(env):
        raw = open(env).read()
        for key in ("SQL_CONNECTION_STRING", "VISION_ENDPOINT", "VISION_KEY",
                    "FOUNDRY_ENDPOINT", "FOUNDRY_KEY", "STORAGE_CONNECTION_STRING"):
            if os.environ.get(key):
                continue
            m = re.search(rf'{key}["\']?\s*[:=]\s*["\']?(.+)', raw)
            if not m:
                continue
            # Cut at the first quote, encoded quote, or line end. FOUNDRY_ENDPOINT
            # in .env closes with a literal "%22" instead of a quote character, so
            # a plain quote-delimited match runs on past the value and swallows the
            # next line — which produced a 404 on every model call. Do not split on
            # whitespace: SQL_CONNECTION_STRING legitimately contains spaces.
            value = re.split(r'%22|["\'\r\n]', m.group(1))[0].strip().rstrip(",")
            if value:
                os.environ[key] = urllib.parse.unquote(value)


def install_pytds_shim():
    """Let db.py run without the Microsoft ODBC driver installed.

    db.py is written for pyodbc: '?' placeholders and params passed as varargs.
    pytds wants '%s' and a sequence. Rather than fork the queries — which is how
    the API's behaviour and this script's behaviour quietly diverge — translate
    at the cursor. No-op when pyodbc is present, which is the case on Azure.
    """
    try:
        import pyodbc  # noqa: F401
        return "pyodbc"
    except ImportError:
        pass

    import ssl
    import types

    import pytds

    # db.py does `import pyodbc` at module scope and catches pyodbc.IntegrityError,
    # so it cannot even be imported without the driver. Stand in a stub whose
    # exception classes are pytds's real ones — then db.py's except clauses still
    # catch what they are meant to catch rather than silently never matching.
    stub = types.ModuleType("pyodbc")
    stub.Error = pytds.Error
    stub.IntegrityError = pytds.IntegrityError
    stub.connect = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("pyodbc is stubbed; db.get_connection is patched below")
    )
    sys.modules.setdefault("pyodbc", stub)

    import db as _db

    class Cursor:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *params):
            if len(params) == 1 and isinstance(params[0], (list, tuple)):
                params = tuple(params[0])
            self._inner.execute(sql.replace("?", "%s"), params or None)
            return self

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class Connection:
        def __init__(self, inner):
            self._inner = inner

        def cursor(self):
            return Cursor(self._inner.cursor())

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._inner.close()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    kv = {}
    for part in os.environ["SQL_CONNECTION_STRING"].split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k.strip().lower()] = v.strip()
    host, _, port = kv.get("server", "").replace("tcp:", "").partition(",")

    def get_connection():
        return Connection(pytds.connect(
            dsn=host, port=int(port) if port else 1433, database=kv.get("database"),
            user=kv.get("uid") or kv.get("user id"),
            password=kv.get("pwd") or kv.get("password"),
            cafile=ssl.get_default_verify_paths().openssl_cafile,
            validate_host=True, autocommit=False, login_timeout=30,
        ))

    _db.get_connection = get_connection
    return "pytds"


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def sessions_for(date_str):
    today = get_json(f"{API}/api/today?date={date_str}")
    return [s["session_id"] for s in (today.get("out_session"), today.get("in_session")) if s]


def main(argv):
    dry_run = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]

    load_env()
    driver = install_pytds_shim()

    import agent
    import db  # noqa: F401  (imported for its patched get_connection)
    import vision

    if not args:
        args = [datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")]

    session_ids = []
    for a in args:
        session_ids.extend(sessions_for(a) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a) else [a])

    print(f"driver: {driver}   sessions: {session_ids or '(none)'}"
          f"{'   DRY RUN — nothing will be written' if dry_run else ''}\n")

    changed = 0
    for sid in session_ids:
        events = get_json(f"{API}/api/events?session_id={urllib.parse.quote(sid)}")["events"]
        print(f"{sid}  ({len(events)} photos)")
        for ev in events:
            before = {d["device_type"]: d["count"] for d in ev["devices"]}
            photo = urllib.request.urlopen(ev["photo_url"], timeout=120).read()

            result = agent.count_devices(photo, vision.analyze_image(photo))
            if result["devices"] is None:
                print(f"  seq{ev['sequence']} {ev['zone']:<8} agent unavailable — left as-is")
                continue

            after = {d["device_type"]: d["count"] for d in result["devices"]}
            arrow = "same" if after == before else "CHANGED"
            print(f"  seq{ev['sequence']} {ev['zone']:<8} {before or '{}'} -> {after or '{}'}"
                  f"  conf={result['confidence']}  [{arrow}]")

            if after != before:
                changed += 1
            if not dry_run:
                db.save_detections(ev["event_id"], result["devices"], result["confidence"],
                                   result["needs_review"], result["reason"])

        if not dry_run:
            # Same call the API makes after saving detections, so a re-analysed
            # session ends up flagged exactly as a freshly captured one would.
            db.run_zone_overview_cross_check(sid)
        print()

    print(f"{changed} photo(s) would change." if dry_run else f"{changed} photo(s) updated.")


if __name__ == "__main__":
    main(sys.argv[1:])
