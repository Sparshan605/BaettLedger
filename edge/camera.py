"""
The camera. One wrapper, one open device, one get_frame().

Hardware: Freenove OV5647 on the CSI port. Verified sharp at 40-60 cm, so the
lens needs no adjustment. Capture is 1920x1080 stills.

picamera2 allows only one process to hold the camera. Opening it a second time
raises a device-busy error that reads like a wiring fault and costs an hour to
diagnose, so this module keeps a single instance and everything else calls
get_frame(). Do not instantiate Picamera2 anywhere else.
"""
import os
import time
from pathlib import Path

from picamera2 import Picamera2

from edge import CHECK_ZONE, COUNT_ZONE

# Seconds to let auto-exposure and auto-white-balance settle after the sensor
# starts. Only paid once, on the first capture. The tailgate is dim and photos
# taken immediately after start() come out underexposed.
_WARMUP_SECONDS = 2.0

# Mean luminance (0-255) below which a frame has no usable scene in it. A lens
# cap, a covered sensor or an unlit tailgate all land around 3-5. Vision cannot
# classify a photo like that, so it is worth catching on the Pi.
DARK_THRESHOLD = 12.0

# Exposure compensation, in stops, handed to the sensor's auto-exposure. 0.0 is
# whatever the AE algorithm picks on its own; -1.0 is one stop darker.
#
# Auto-exposure meters the WHOLE frame, and most of this frame is truck bed. A
# bright venue — daylight through a bay door, overhead floods — drives the AE to
# expose for that background and blows out the devices themselves: white bands
# on the cones merge into one another and a stack stops being countable. Pulling
# a stop out protects the highlights, which is where the countable detail lives.
#
# Override per site without editing code: CAMERA_EV=-1.5 in the service
# environment. Going too far the other way costs more than it saves — under
# DARK_THRESHOLD the frame is rejected outright, and the agent now treats a dim
# photo as a reason to flag for review.
EXPOSURE_EV = float(os.environ.get("CAMERA_EV", "-1.0"))

_camera = None


def _open():
    """Open the camera once and keep it open. Subsequent calls reuse it."""
    global _camera
    if _camera is None:
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(main={"size": (1920, 1080)}))
        cam.start()
        # Set before the warm-up sleep, not after: AE needs those two seconds to
        # converge ON the compensated target. Applied after, the first capture
        # of a session is still metered for the uncompensated scene.
        if EXPOSURE_EV:
            cam.set_controls({"ExposureValue": EXPOSURE_EV})
        time.sleep(_WARMUP_SECONDS)
        _camera = cam
    return _camera


def warm_up():
    """Open and settle the camera ahead of time.

    The first get_frame() otherwise pays the warm-up, which would delay the
    photo for the very first device of a session. main.py calls this when a
    session opens so the cost lands while nobody is waiting.
    """
    _open()


def get_frame(path):
    """Capture one still to `path`. Returns the Path it wrote.

    Creates the parent directory if needed. The first call takes about two
    seconds (warm-up) unless warm_up() was called earlier; after that a capture
    is fast enough to keep up with devices passing the beam one at a time.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _open().capture_file(str(path))
    return path


# How much of the frame the close-up keeps, per side. 0.8 trims the outer 10%
# off every edge: enough to lose the tailgate rails and whatever is on the
# ground behind the truck, not so much that a cone at the end of the row falls
# outside it.
#
# This is the number to change at the demo if the cross-check keeps firing. The
# close-up must still contain the ENTIRE load — it is meant to see the same
# devices as the wide shot through a tighter frame, so that a disagreement means
# something real. Crop past the load and it will always read low, and every
# session gets flagged for a mismatch that is really just the crop.
CLOSEUP_SCALE = 0.8


def split_capture(path, out_dir=None):
    """Cut one capture into the two images an inventory uploads.

    Returns [(zone, Path), ...]: the untouched frame as `wide`, then a centre
    crop of it as `closeup`.

    The wide entry is the original file, not a copy. It is the only image that
    sees the whole load, so it is the one the backend counts. The close-up is
    the same load through a tighter frame, counted independently and never added
    to the total — two estimates that disagree flag the session for a human
    rather than being silently averaged (docs/api.md §6a).
    """
    from PIL import Image

    path = Path(path)
    out_dir = Path(out_dir) if out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(path) as im:
        width, height = im.size
        # Size the crop first, then centre it. Deriving the margin instead
        # (int(width * (1 - SCALE) / 2)) reads fine and is wrong: 1 - 0.8 is
        # 0.199999... in binary, which truncates a pixel low on each side and
        # quietly hands back 1538x866 where 1536x864 was asked for.
        crop_w = round(width * CLOSEUP_SCALE)
        crop_h = round(height * CLOSEUP_SCALE)
        left = (width - crop_w) // 2
        top = (height - crop_h) // 2
        crop_path = out_dir / f"{path.stem}_{CHECK_ZONE}.jpg"
        im.crop((left, top, left + crop_w, top + crop_h)).save(
            crop_path, "JPEG", quality=90
        )

    return [(COUNT_ZONE, path), (CHECK_ZONE, crop_path)]


def exposure_info():
    """Current exposure time (us), analogue gain and estimated lux.

    Useful for telling 'the sensor is broken' apart from 'there is no light':
    a working sensor in the dark shows a long exposure, a high gain and a
    near-zero lux.
    """
    md = _open().capture_metadata()
    return {
        "exposure_us": md.get("ExposureTime"),
        "gain": md.get("AnalogueGain"),
        "lux": md.get("Lux"),
    }


def brightness(path):
    """Mean luminance of a captured JPEG, 0 (black) to 255 (white)."""
    from PIL import Image, ImageStat

    with Image.open(path) as im:
        stat = ImageStat.Stat(im.convert("L"))
    return stat.mean[0], stat.stddev[0]


def close():
    """Release the camera. Call on shutdown so the next run can open it."""
    global _camera
    if _camera is not None:
        _camera.close()
        _camera = None


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/edge_camera_test.jpg")

    print(f"capturing to {out} ...")
    start = time.time()
    get_frame(out)
    first = time.time() - start

    start = time.time()
    get_frame(out.with_name(out.stem + "_2.jpg"))
    second = time.time() - start

    exp = exposure_info()
    mean, stddev = brightness(out)
    size = out.stat().st_size
    close()

    print()
    print(f"  first capture : {first:.2f}s  (includes {_WARMUP_SECONDS:.0f}s warm-up)")
    print(f"  second capture: {second:.2f}s")
    print(f"  file          : {out}  ({size / 1024:.0f} KB)")
    print(f"  exposure      : {exp['exposure_us']} us   gain {exp['gain']}   lux {exp['lux']}")
    print(f"  brightness    : mean {mean:.1f}/255   stddev {stddev:.1f}")
    print()

    if size < 10_000:
        print("FAIL — file is suspiciously small. Check the CSI ribbon seating.")
        sys.exit(1)

    if mean < DARK_THRESHOLD:
        print(f"FAIL — frame is black (mean {mean:.1f}, below {DARK_THRESHOLD}).")
        print("       The sensor is working; no light is reaching it. Check, in order:")
        print("         1. the plastic film or lens cap still on the lens")
        print("         2. the camera facing a wall, the desk, or its own ribbon")
        print("         3. the room being too dark — the OV5647 has little dynamic range")
        print("       A high gain with near-zero lux above confirms 'dark', not 'broken'.")
        sys.exit(1)

    if stddev < 5.0:
        print(f"FAIL — frame is a flat field (stddev {stddev:.1f}). Lit, but nothing in view.")
        sys.exit(1)

    # The two images an inventory actually uploads.
    from PIL import Image

    frames = split_capture(out)
    print("  captures:")
    sizes = {}
    for zone, frame_path in frames:
        with Image.open(frame_path) as im:
            sizes[zone] = im.size
        w, h = sizes[zone]
        kb = frame_path.stat().st_size / 1024
        role = "counted" if zone == COUNT_ZONE else "cross-check"
        print(f"    {zone:<9} {w:>5}x{h:<5} {kb:>6.0f} KB  {role:<11} {frame_path.name}")
    print()

    with Image.open(out) as im:
        full_width, full_height = im.size

    if len(frames) != 2:
        print(f"FAIL — expected 2 frames, got {len(frames)}.")
        sys.exit(1)

    if sizes[COUNT_ZONE] != (full_width, full_height):
        print(f"FAIL — {COUNT_ZONE} is {sizes[COUNT_ZONE]}, not the full {full_width}x{full_height}.")
        print("       The counted image must be the uncropped frame — it is the only")
        print("       one that sees the whole load.")
        sys.exit(1)

    crop_w, crop_h = sizes[CHECK_ZONE]
    if not (0 < crop_w < full_width and 0 < crop_h < full_height):
        print(f"FAIL — {CHECK_ZONE} is {crop_w}x{crop_h}, not a crop of {full_width}x{full_height}.")
        sys.exit(1)

    print(f"  {COUNT_ZONE} is the full frame; {CHECK_ZONE} keeps the middle "
          f"{CLOSEUP_SCALE:.0%} ({crop_w}x{crop_h})")
    print("\nPASS — camera works, the frame has a real scene, and it splits cleanly.")
    print("\nLook at both files before the demo. The close-up must still contain the")
    print(f"WHOLE load — if it clips devices, raise CLOSEUP_SCALE above {CLOSEUP_SCALE}.")
