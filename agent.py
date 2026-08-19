"""
Count Agent (count-agent, gpt-4o) — v3, the model looks at the PHOTO.

Until Aug 14 this sent Azure AI Vision's objects+tags JSON and nothing else, so
the count could never be better than a generic object detector. On a real load
Vision returned exactly one object — `stop sign` — and no cones or barricades at
all, so the agent dutifully reported "1 sign" for a truck bed holding four cones
and two barricades. It was not wrong; it was answering the only question it had
been asked.

count-agent is gpt-4o, which is multimodal. It now receives the JPEG itself, and
Vision's detections come along only as a hint that is explicitly labelled as
unreliable. On that same photo the count went from `1 sign` to
`1 sign, 4 cone, 2 barricade` at 0.90 confidence.

api.md §6 — system prompt is fixed, confidence threshold applied in Python,
malformed JSON gets one retry then falls back to no detections + needs_review.
"""
import base64
import json
import logging
import os

import requests

APPROVED_DEVICE_TYPES = {"cone", "sign", "barricade", "delineator", "barrel", "unknown"}

# "high" tiles the image at full resolution instead of downsampling it to a
# single 512px thumbnail. A cone at the back of the bed is a handful of pixels
# in a 512px version of a 1920x1080 frame, which is the difference between
# counting it and not. Costs about 1.1k prompt tokens per photo.
IMAGE_DETAIL = "high"

SYSTEM_PROMPT = """You count traffic-control devices loaded in the back of a truck.

You are shown ONE photo of the load. It is either the wide shot of the whole bed
or a tighter close-up of the same load. Devices may be stacked, nested, tipped
over, leaning together or partly hidden behind each other.

Count EVERY device you can see.

Reply with ONLY this JSON object, no prose and no code fence. (The literal word
"json" must stay in this prompt: the API rejects the request outright when
response_format is json_object and no message mentions it.)
{"devices": [{"device_type": "cone", "count": 3}],
 "confidence": 0.0, "needs_review": false, "reason": "..."}

device_type must be exactly one of: cone, sign, barricade, delineator, barrel, unknown
  cone        traffic cone — square base, tapering to a point, ANY colour
  sign        any sign on a stand, post or handheld paddle (STOP/SLOW included)
  barricade   horizontal striped panel, trestle or A-frame barricade
  delineator  slim vertical tube post, also called a candlestick or tubular marker
  barrel      drum / channelizer barrel — cylindrical, waist high, banded, often
              with a ballast ring at the foot. ANY colour.
  unknown     clearly a traffic-control device but none of the above. This is a
              last resort: if it matches a type above, name that type.

Colour is NOT identifying. These devices come in orange, yellow, lime, green,
white, pink and faded-grey. Judge shape and function only. A yellow cone is a
cone; a yellow drum is a barrel. Never answer unknown, and never lower your
confidence, because the colour was not the one you expected.

Stacked and nested devices are the normal case, not a problem case. A stack of
cones is a stack of cones — count it and stay confident. To count a nested
stack: count the visible rims/ridges up the side of the stack, or count the
bases; a clean stack of N cones shows N base flanges. If you can count the
stack, that is a confident answer, not a reviewable one.

Rules:
- One entry per type. A load with cones and a sign has two entries. Return an
  empty devices list only if there is genuinely nothing in the photo.
- count is how many of that type you can SEE in this photo. Nested or stacked
  cones still count individually — count the visible bases or tips.
- Do not estimate what might be hidden behind the front row, and do not round
  to a tidy number.
- confidence is 0.0-1.0 for the photo as a whole. Base it on how well you can
  SEE the load — sharpness, lighting, framing — not on how unusual the devices
  look. A clear, well-lit photo of an ordinary load is 0.9+ even when the
  devices are stacked or an unusual colour.
- Set needs_review true, and say why in reason, ONLY when: the image is blurred
  or dark, devices are so tangled or occluded that you cannot arrive at a
  number, devices are cut off by the frame, or you see a device that fits none
  of the types above. Stacking, nesting, tipping, leaning and unexpected
  colours are not by themselves reasons for review.
- Ignore any people in the photo entirely. Never describe or count them.
- Never guess. Unsure means needs_review true."""

CONFIDENCE_THRESHOLD = 0.80


def _hint_from_vision(vision_result: dict | None) -> str:
    """Vision's detections, framed as the weak signal they actually are.

    Handed over without this framing the model anchors on them and reproduces
    the exact undercount this rewrite exists to fix — Vision reports the stop
    sign confidently and stays silent about six other devices, which reads like
    "there is one device here" unless you say otherwise.
    """
    if not vision_result:
        return ""
    objects = [o.get("object") for o in vision_result.get("objects", []) if o.get("object")]
    if not objects:
        return ""
    return (
        "\n\nA generic object detector reported: "
        + ", ".join(objects)
        + ". It does not recognise traffic cones, delineators, barrels or "
        "barricades at all, and it is easily confused by colour, so treat it as a "
        "partial hint and never as a limit. The photo is authoritative."
    )


def _extract_json(text: str) -> dict:
    """Parse the model's reply, tolerating a ```json fence around it.

    JSON mode is requested below, but the fence showed up the moment an image
    was added to the request, and one stray fence costs a whole inventory.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _call_model(photo_bytes: bytes, vision_result: dict | None) -> str:
    endpoint = os.environ["FOUNDRY_ENDPOINT"]
    key = os.environ["FOUNDRY_KEY"]
    headers = {"api-key": key, "Content-Type": "application/json"}
    b64 = base64.b64encode(photo_bytes).decode()
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Count every traffic-control device in this photo."
                        + _hint_from_vision(vision_result),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": IMAGE_DETAIL,
                        },
                    },
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": 400,
        # Belt and braces with _extract_json above.
        "response_format": {"type": "json_object"},
    }
    # Vision analysis of a 1080p frame is slower than a JSON round-trip; the old
    # 20s timeout would have cut real answers off partway.
    resp = requests.post(endpoint, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _normalize_devices(raw_devices) -> list[dict]:
    """Clamp every entry's device_type to the approved set; unknown types flip needs_review."""
    normalized = []
    flip_needs_review = False
    for d in raw_devices:
        device_type = d.get("device_type")
        if device_type not in APPROVED_DEVICE_TYPES:
            device_type = "unknown"
            flip_needs_review = True
        try:
            count = int(d.get("count", 0))
        except (TypeError, ValueError):
            count = 0
            flip_needs_review = True
        normalized.append({"device_type": device_type, "count": count})
    return normalized, flip_needs_review


def count_devices(photo_bytes: bytes, vision_result: dict | None = None) -> dict:
    """
    Returns {"devices": [...], "confidence", "needs_review", "reason"}.
    Never raises — every failure path returns a valid, safely-flagged dict
    because the count_event row already exists and must survive (api.md §6).

    vision_result is optional now. It used to be the ONLY input, so Vision being
    down meant no count was possible and the event was left unanalyzed; the
    photo is the input today, so a Vision outage costs a hint and nothing more.
    devices=None is returned only when the agent itself cannot be reached, and
    the caller must then skip save_detections so analyzed_at stays NULL and the
    dashboard shows "pending" rather than a fabricated "0" (api.md §1 rule 2).
    """
    if not photo_bytes:
        return {"devices": None, "confidence": None,
                "needs_review": False, "reason": "no photo to analyse"}

    for attempt in range(2):  # one retry on malformed output
        try:
            raw = _call_model(photo_bytes, vision_result)
            parsed = _extract_json(raw)

            devices, flip_needs_review = _normalize_devices(parsed.get("devices", []))
            confidence = float(parsed.get("confidence", 0.0))
            needs_review = bool(parsed.get("needs_review", False)) or flip_needs_review
            # Threshold enforced here in code, not trusted from the model (api.md §6).
            if confidence < CONFIDENCE_THRESHOLD:
                needs_review = True

            return {
                "devices": devices,
                "confidence": confidence,
                "needs_review": needs_review,
                "reason": parsed.get("reason"),
            }
        except (json.JSONDecodeError, KeyError, ValueError, requests.RequestException) as e:
            logging.warning("Count Agent attempt %s failed: %s", attempt + 1, e)

    return {"devices": [], "confidence": None,
            "needs_review": True, "reason": "agent returned invalid output"}
