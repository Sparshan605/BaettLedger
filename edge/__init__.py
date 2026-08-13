"""
BaettLedger edge package — everything that runs on the Raspberry Pi.

Owner: Sparshan. The cloud side lives in function_app.py (Shivang) and the
dashboard in src/ (Shivang); see docs/api.md for the contract between them.

Module map, in the order they get built:
    camera.py    one get_frame(path) around picamera2
    lcd.py       one show(line1, line2) on the 16x2 I2C display
    trigger.py   wait_for_event() — button-backed today, sensor-backed later
    sensor.py    the HC-SR04 implementation of that same interface
    feedback.py  buzzer beeps
    store.py     SQLite queue of events waiting to upload
    uploader.py  drains the queue to the Azure API
    main.py      the loop that ties them together

There is exactly ONE of each of these. Before adding a helper here, grep for an
existing one — a second camera wrapper or a second capture loop will open the
camera twice, and picamera2 reports that as a device-busy error that looks like
a wiring fault.
"""

__version__ = "0.1.0"

# Identifies this Pi to the API. Must match what the backend expects; it is part
# of the idempotency key (device_id, session_id, sequence) in docs/api.md §4.
DEVICE_ID = "baettledger-01"

# Approved device types (proposal §6). The Count Agent may only return one of
# these plus "unknown". Kept here so the Pi and the docs cannot drift.
DEVICE_TYPES = ("cone", "sign", "barricade", "delineator")
