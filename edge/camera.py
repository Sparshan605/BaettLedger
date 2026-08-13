"""
The camera. One wrapper, one open device, one get_frame().

Hardware: Freenove OV5647 on the CSI port. Verified sharp at 40-60 cm, so the
lens needs no adjustment. Capture is 1920x1080 stills.

picamera2 allows only one process to hold the camera. Opening it a second time
raises a device-busy error that reads like a wiring fault and costs an hour to
diagnose, so this module keeps a single instance and everything else calls
get_frame(). Do not instantiate Picamera2 anywhere else.
"""
import time
from pathlib import Path

from picamera2 import Picamera2

# Seconds to let auto-exposure and auto-white-balance settle after the sensor
# starts. Only paid once, on the first capture. The tailgate is dim and photos
# taken immediately after start() come out underexposed.
_WARMUP_SECONDS = 2.0

# Mean luminance (0-255) below which a frame has no usable scene in it. A lens
# cap, a covered sensor or an unlit tailgate all land around 3-5. Vision cannot
# classify a photo like that, so it is worth catching on the Pi.
DARK_THRESHOLD = 12.0

_camera = None


def _open():
    """Open the camera once and keep it open. Subsequent calls reuse it."""
    global _camera
    if _camera is None:
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(main={"size": (1920, 1080)}))
        cam.start()
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

    print("PASS — camera works and the frame has a real scene in it.")
