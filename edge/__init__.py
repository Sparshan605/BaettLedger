"""
BaettLedger edge package — everything that runs on the Raspberry Pi.

Owner: Sparshan. The cloud side lives in function_app.py (Shivang) and the
dashboard in src/ (Shivang); see docs/api.md for the contract between them.

Module map, in the order they get built:
    camera.py    one get_frame(path) around picamera2
    lcd.py       one show(line1, line2) on the 16x2 I2C display
    trigger.py   wait_for_press() — one press, one photo, on GPIO27
    feedback.py  buzzer beeps
    store.py     SQLite queue of events waiting to upload
    uploader.py  drains the queue to the Azure API
    main.py      the loop that ties them together

There is exactly ONE of each of these. Before adding a helper here, grep for an
existing one — a second camera wrapper or a second capture loop will open the
camera twice, and picamera2 reports that as a device-busy error that looks like
a wiring fault.

There is no sensor.py. The original design had devices breaking an ultrasonic
beam one at a time; we now photograph the loaded truck bed in one shot instead,
so there is no beam to break and the dead HC-SR04 blocks nothing.
"""

__version__ = "0.1.0"

from pathlib import Path

# Everything the Pi writes at runtime lives here, deliberately OUTSIDE the repo:
# photos and the SQLite queue are data, not source, and keeping them out means a
# stray `git add -A` cannot commit a few megabytes of JPEGs.
DATA_DIR = Path.home() / "baettledger"

# Identifies this Pi to the API. Must match what the backend expects; it is part
# of the idempotency key (device_id, session_id, sequence) in docs/api.md §4.
DEVICE_ID = "baettledger-01"

# Approved device types (proposal §6). The Count Agent may only return one of
# these plus "unknown". Kept here so the Pi and the docs cannot drift.
DEVICE_TYPES = ("cone", "sign", "barricade", "delineator")

# One inventory = two photos of one capture, in this order.
#
# WIDE is the frame exactly as the sensor saw it, and it is the one that counts:
# it is the only image that sees the whole load, so the inventory total is its
# number alone.
COUNT_ZONE = "wide"

# CLOSEUP is that same frame with the outer margin trimmed off — the load
# without the tailgate edges or the background behind it. It is counted
# independently and NEVER added to the total. Its entire job is to be a second
# opinion: if it and the wide shot disagree by more than a device or two, then
# something outside the load is being counted or something inside it is being
# missed, and the inventory gets flagged for a human instead of trusted.
CHECK_ZONE = "closeup"

CAPTURE_SEQUENCE = (COUNT_ZONE, CHECK_ZONE)

# This replaced a left/middle/right split plus an overview. Thirds tiled the
# frame exactly, which made the sum valid by construction — but a device
# straddling a boundary was sliced in half in two crops, and every press put
# four photos through Vision. Two photos halves the demo wait and never cuts a
# device in half. The names below are the retired ones; the backend still
# accepts them so the sessions already in the database keep totalling correctly.
LEGACY_ZONES = ("left", "middle", "right", "overview")
