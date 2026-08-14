"""
Sends a real photo through POST /api/events, exercising the full pipeline:
Blob upload -> DB row insert -> Vision -> Count Agent -> detections saved.

Usage:
    python test_event_upload.py path\to\photo.jpg left
    python test_event_upload.py path\to\photo.jpg middle
    python test_event_upload.py path\to\photo.jpg right
    python test_event_upload.py path\to\photo.jpg overview

Run it four times (once per zone) with the SAME session_id below to build
one full inventory, then check /api/events?session_id=... to see the results.
"""
import sys
import json
import time
import requests

BASE_URL = "http://localhost:7071"
SESSION_ID = "test-session-003"   # keep the same across all 4 zone calls
DEVICE_ID = "baettledger-01"

with open("local.settings.json") as f:
    settings = json.load(f)
DEVICE_KEY = settings["Values"]["DEVICE_KEY"]

SEQUENCE_BY_ZONE = {"left": 1, "middle": 2, "right": 3, "overview": 4}


def open_session_if_needed():
    resp = requests.post(
        f"{BASE_URL}/api/sessions",
        headers={"x-device-key": DEVICE_KEY},
        json={
            "device_id": DEVICE_ID,
            "session_id": SESSION_ID,
            "session_type": "OUT",
            "opened_at": "2026-08-14T11:00:00Z",
        },
    )
    print(f"open_session -> {resp.status_code} {resp.text}")


def send_event(photo_path, zone):
    sequence = SEQUENCE_BY_ZONE[zone]
    metadata = {
        "device_id": DEVICE_ID,
        "session_id": SESSION_ID,
        "sequence": sequence,
        "zone": zone,
        "captured_at": "2026-08-14T11:0" + str(sequence) + ":00Z",
    }

    with open(photo_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/api/events",
            headers={"x-device-key": DEVICE_KEY},
            data={"metadata": json.dumps(metadata)},
            files={"photo": ("photo.jpg", f, "image/jpeg")},
        )
    print(f"send_event zone={zone} seq={sequence} -> {resp.status_code} {resp.text}")
    return resp


def check_results():
    print("\nWaiting 8s for Vision + Count Agent to finish...")
    time.sleep(8)
    resp = requests.get(f"{BASE_URL}/api/events", params={"session_id": SESSION_ID})
    print(f"\nGET /api/events?session_id={SESSION_ID} ->")
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python test_event_upload.py <path-to-photo.jpg> <left|middle|right|overview>")
        sys.exit(1)

    photo_path, zone = sys.argv[1], sys.argv[2]
    if zone not in SEQUENCE_BY_ZONE:
        print(f"zone must be one of {list(SEQUENCE_BY_ZONE)}")
        sys.exit(1)

    open_session_if_needed()
    send_event(photo_path, zone)
    check_results()
