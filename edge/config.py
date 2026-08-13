"""
Settings, read from a .env file that is never committed.

Two values, both supplied by the cloud side: the base URL of the Function App
and the device key it authenticates with (docs/azure-setup.md §3). Protsahan
generates the key and sends it privately; it goes in .env and nowhere else.

Deliberately not using python-dotenv — this is a dozen lines and one fewer
dependency to install on a Pi that has to work on demo day.
"""
import os
from pathlib import Path

# Repo root: edge/config.py -> edge/ -> repo
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load(path=None):
    """Read .env into a dict. Missing file is fine — returns what os.environ has."""
    values = {}
    env_path = Path(path or ENV_PATH)
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    # A real environment variable wins over the file, which makes it easy to
    # point at a mock server for a test run without editing anything.
    for key in ("API_URL", "DEVICE_KEY"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def api_url(path=None):
    """Base URL with no trailing slash, or None if unset."""
    url = load(path).get("API_URL", "").rstrip("/")
    return url or None


def device_key(path=None):
    return load(path).get("DEVICE_KEY") or None


def is_configured(path=None):
    return bool(api_url(path) and device_key(path))


if __name__ == "__main__":
    print(f".env path : {ENV_PATH}")
    print(f"exists    : {ENV_PATH.exists()}")
    print(f"API_URL   : {api_url() or '(unset)'}")
    key = device_key()
    print(f"DEVICE_KEY: {'set, ' + str(len(key)) + ' chars' if key else '(unset)'}")
    print()
    print("configured — uploader can run" if is_configured()
          else "not configured — copy .env.example to .env and fill it in")
