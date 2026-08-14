"""
The loop. Press the button, get an inventory.

This is the offline milestone: it needs no internet, no Azure and no partner
code. One press captures the truck bed, splits it into three non-overlapping
zones plus an overview, queues all four for upload, and shows the result on the
LCD. uploader.py drains that queue later, whenever there is a network.

    idle    |BaettLedger     |
            |Ready: OUT    q0|      q0 = nothing waiting to upload

    press   |OUT        3..  |
            |Hold steady     |      time to aim and get your hand out of frame

    capture |OUT captured    |
            |4 photos queued |

Direction is not asked for. store.next_direction() reads the day's history: the
morning inventory is OUT, the evening one IN.

Run it:
    python3 -m edge.main            normal, waits for presses
    python3 -m edge.main --once     one inventory now, no button (for testing)
"""
import sys
import time
from pathlib import Path

from edge import DATA_DIR, camera, config, lcd, store, trigger, uploader

PHOTO_DIR = DATA_DIR / "photos"

# Seconds between the press and the shutter. Long enough to aim at the load and
# get your hand out of frame, short enough that nobody wonders if it registered.
COUNTDOWN_SECONDS = 3

# How often the idle screen redraws. Also how often the queue count refreshes,
# which is the only sign the uploader is making progress.
IDLE_REFRESH_SECONDS = 5


def _photo_path(session_id):
    stamp = store.utc_now().replace(":", "").replace("-", "")
    return PHOTO_DIR / f"{session_id}_{stamp}.jpg"


def run_inventory(countdown=COUNTDOWN_SECONDS):
    """Capture one inventory: open a session, shoot, split, queue, close.

    Returns the session row and the queued events. Raises nothing the caller
    needs to handle beyond hardware failure — the queue write is the last step
    that can fail, and it is a local commit.
    """
    session = store.open_session()
    direction = session["session_type"]

    for remaining in range(countdown, 0, -1):
        lcd.show(f"{direction}        {remaining}..", "Hold steady")
        time.sleep(1)

    lcd.show(f"{direction} capturing", "")
    path = camera.get_frame(_photo_path(session["session_id"]))
    frames = camera.split_zones(path)

    # Queue before anything else can go wrong. Once these rows are committed
    # the photos are safe even if the Pi loses power on the next line.
    rows = store.add_inventory(session["session_id"], frames)
    store.close_session(session["session_id"])

    lcd.show(f"{direction} captured", f"{len(rows)} photos queued")
    return session, rows


def _idle_screen():
    """Waiting for a press. Says which half of the day comes next.

    A run is two presses: OUT loads the truck, IN brings it back. The operator
    should never have to remember which one they are on, so the direction is on
    the screen rather than in their head. q is the upload backlog.
    """
    direction = store.next_direction()
    prompt = "Press: load OUT" if direction == "OUT" else "Press: return IN"

    # OFFLINE is the one thing the crew must be able to see without a phone
    # (proposal §8). last_online is whatever the uploader thread saw on its
    # most recent pass, so this costs nothing to read.
    queued = store.pending_count()
    if uploader.last_online is False:
        status = f"OFFLINE     q{queued:>2}"
    else:
        status = f"{direction:<3}          q{queued:>2}"
    lcd.show(prompt, status)


def _after_inventory(direction, rows):
    """The screen shown right after a capture, before returning to idle.

    OUT is only half a run, so it points at the next step. IN completes the
    pair the dashboard reconciles, so it says so — otherwise there is no signal
    on the device that the day's comparison is ready.
    """
    lcd.show(f"{direction} captured", f"{len(rows)} photos queued")
    time.sleep(2)
    if direction == "OUT":
        lcd.show("OUT done", "Next: return IN")
    else:
        lcd.show("Day complete", "OUT + IN sent")
    time.sleep(3)


def _recover_open_sessions():
    """Close sessions left open by a power cut, so the next press starts clean.

    Their photos are already queued and will still upload; only the session
    close was lost. Losing that would leave the dashboard showing a session
    that never ends.
    """
    stale = store.open_sessions()
    for session in stale:
        store.close_session(session["session_id"])
    return stale


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    once = "--once" in argv

    store.init()
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)

    lcd.show("BaettLedger", "starting...")

    try:
        camera.warm_up()  # pay the 2s settle now, not on the first capture
    except RuntimeError as exc:
        # Almost always "Device or resource busy": something else already holds
        # the camera, usually a manual `python3 -m edge.main` left running while
        # the service is also up. picamera2 reports it as a bare RuntimeError
        # with a stack trace, which reads like a wiring fault and costs an hour.
        # Say what it actually is, on the display, where you can see it without
        # a laptop. systemd restarts us, so this recovers by itself once the
        # other process exits.
        lcd.show("Camera busy", "2nd run open?")
        print(f"camera unavailable: {exc}", file=sys.stderr)
        print("something else holds the camera. Check for another "
              "`python3 -m edge.main`, or `sudo systemctl stop baettledger`.",
              file=sys.stderr)
        lcd.close(blank=False)
        return 1

    stale = _recover_open_sessions()
    if stale:
        lcd.show("Recovered", f"{len(stale)} open session")
        time.sleep(2)

    if once:
        session, rows = run_inventory()
        print(f"session {session['session_id']} ({session['session_type']})")
        for row in rows:
            print(f"  seq {row['sequence']}  {row['zone']:<9} {row['photo_path']}")
        print(f"pending upload: {store.pending_count()}")
        _after_inventory(session["session_type"], rows)
        lcd.close(blank=False)  # leave the result readable after we exit
        return 0

    # Upload in the background so the dashboard fills in while the demo runs.
    # Without this the queue only drains when someone runs edge.uploader by
    # hand, which is fine for testing and useless in front of an audience.
    #
    # It is a daemon thread and every pass swallows its own errors, so a dead
    # network cannot stop the Pi counting — captures still queue and replay
    # when the connection comes back (proposal §8).
    uploader_thread = None
    if config.is_configured():
        uploader_thread, _ = uploader.start()
        print("uploader running in the background")
    else:
        print("no API_URL/DEVICE_KEY — capturing offline, nothing will upload")

    print("waiting for presses. Ctrl+C to stop.")
    try:
        while True:
            _idle_screen()
            if not trigger.wait_for_press(timeout=IDLE_REFRESH_SECONDS):
                continue  # timeout: redraw so the queue count stays current
            session, rows = run_inventory()
            print(f"{session['session_type']}  {session['session_id']}  "
                  f"{len(rows)} queued  (pending {store.pending_count()})")
            _after_inventory(session["session_type"], rows)
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        lcd.show("BaettLedger", "stopped")
        camera.close()
        trigger.close()
        lcd.close(blank=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
