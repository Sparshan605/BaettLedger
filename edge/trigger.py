"""
The button. One press, one meaning: capture the next photo.

Hardware: push button on GPIO27 (physical pin 13) to GND, internal pull-up,
pressed reads LOW. gpiozero.Button(27) handles the pull-up itself.

An earlier version distinguished a short press from a long one so the same
button could also switch OUT/IN. That is gone. Press length is a bad thing to
rely on in front of an audience — a 1.33s press meant as a hold registers as a
tap, and there is no way to tell from the outside which one the machine saw.

Nothing needs a second meaning now. A session is a fixed sequence of captures
(edge.CAPTURE_SEQUENCE), so it ends on its own, and direction comes from the
day's history in store.py: the first inventory of the day is OUT, the next IN.
"""
import time

from gpiozero import Button

BUTTON_PIN = 27

# Ignore anything arriving within this window of the last accepted press. One
# device through a bouncy switch, or an operator double-tapping, would
# otherwise capture a zone twice and skip the next one.
DEBOUNCE_SECONDS = 0.6

# Contact bounce is milliseconds and gpiozero filters it in the driver. This is
# a different problem from DEBOUNCE_SECONDS above and needs a much smaller value.
_BOUNCE_SECONDS = 0.05

_button = None
_last_press_at = 0.0


def _open():
    """Claim the GPIO once and keep it."""
    global _button
    if _button is None:
        _button = Button(BUTTON_PIN, bounce_time=_BOUNCE_SECONDS)
    return _button


def wait_for_press(timeout=None):
    """Block until the button is pressed. True on press, False on timeout.

    Returns as soon as the button goes down — it does not wait for release, so
    holding it makes no difference to anything. main.py passes a timeout so it
    can redraw the LCD and let the uploader report progress while it waits.
    """
    global _last_press_at
    button = _open()
    deadline = None if timeout is None else time.monotonic() + timeout

    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return False

        if not button.wait_for_press(timeout=remaining):
            return False

        now = time.monotonic()
        if now - _last_press_at < DEBOUNCE_SECONDS:
            continue  # too soon after the last one; keep waiting

        _last_press_at = now
        return True


def close():
    """Release the GPIO. Call on shutdown."""
    global _button
    if _button is not None:
        _button.close()
        _button = None


if __name__ == "__main__":
    import sys

    button = _open()

    state = "PRESSED" if button.is_pressed else "released"
    print(f"button on GPIO{BUTTON_PIN}, at rest it reads: {state}")
    if button.is_pressed:
        print("\nFAIL — reads pressed with nobody touching it.")
        print("       Check the wiring: one leg to GPIO27, the other to GND.")
        sys.exit(1)

    print("waiting 2s to confirm nothing arrives on its own ...")
    if wait_for_press(timeout=2.0):
        print("\nFAIL — got a press with nobody pressing. Electrical noise or a short.")
        sys.exit(1)
    print("quiet at rest.\n")

    print("Press the button 4 times — however you like, length does not matter.")
    print("This is the real capture sequence, so it also previews the LCD flow.\n")

    from edge import CAPTURE_SEQUENCE

    seen = 0
    try:
        for i, zone in enumerate(CAPTURE_SEQUENCE):
            print(f"  point at {zone.upper():<9} and press ... ", end="", flush=True)
            if not wait_for_press(timeout=60):
                print("(60s with no press — stopping)")
                break
            seen += 1
            print(f"captured {i + 1}/{len(CAPTURE_SEQUENCE)}")
    except KeyboardInterrupt:
        print("\n  stopped.")

    close()

    print()
    if seen == len(CAPTURE_SEQUENCE):
        print(f"PASS — all {seen} presses registered, one per zone, none doubled.")
    elif seen:
        print(f"PARTIAL — {seen} of {len(CAPTURE_SEQUENCE)} presses registered.")
        sys.exit(1)
    else:
        print("FAIL — no presses registered. Check the GPIO27 wiring.")
        sys.exit(1)
