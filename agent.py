"""
Count Agent (aif-baettledger) — v2, zone-based architecture.

A photo now shows ONE ZONE of a loaded truck bed (or the overview), and can
contain several device types at once — stacked, overlapping, partly hidden.
The agent returns a LIST of {device_type, count}, not a single value.
api.md §6 — system prompt is fixed, confidence threshold applied in Python,
malformed JSON gets one retry then falls back to no detections + needs_review.
"""
import os
import json
import logging
import requests

APPROVED_DEVICE_TYPES = {"cone", "sign", "barricade", "delineator", "unknown"}

SYSTEM_PROMPT = """You count traffic-control devices loaded in the back of a truck.

The photo shows ONE ZONE of the truck bed (left, middle, right) or an OVERVIEW
of the whole load. Several devices are visible at once and they may be stacked,
overlapping or partly hidden behind each other.

You will receive object detections and tags from Azure AI Vision.

Reply with ONLY this JSON, no prose:
{"devices": [{"device_type": "cone", "count": 3}],
 "confidence": 0.0, "needs_review": false, "reason": "..."}

Rules:
- device_type must be one of: cone, sign, barricade, delineator, unknown
- Include one entry per type you can see. A zone with cones and a sign has two
  entries. Return an empty devices list if the zone is empty.
- count is how many of that type are visible IN THIS PHOTO
- confidence is 0.0-1.0 for the whole photo
- Set needs_review true and explain in reason when: the image is blurred or
  dark, devices are stacked or overlap so you cannot separate them, devices are
  partly out of frame, or you see a type not in the approved list
- Count only what you can actually see. Do not estimate what might be hidden
  behind the front row, and do not round to a tidy number.
- Ignore any people in the photo entirely. Never describe or count them.
- Never guess. Unsure means needs_review true."""

CONFIDENCE_THRESHOLD = 0.80


def _call_model(vision_result: dict) -> str:
    endpoint = os.environ["FOUNDRY_ENDPOINT"]
    key = os.environ["FOUNDRY_KEY"]
    headers = {"api-key": key, "Content-Type": "application/json"}
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(vision_result)},
        ],
        "temperature": 0,
        "max_tokens": 400,
    }
    resp = requests.post(endpoint, headers=headers, json=body, timeout=20)
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


def count_devices(vision_result: dict | None) -> dict:
    """
    Returns {"devices": [...], "confidence", "needs_review", "reason"}.
    Never raises — every failure path returns a valid, safely-flagged dict
    because the count_event row already exists and must survive (api.md §6).

    vision_result=None means Vision itself failed or was skipped: leave the
    event unanalyzed (caller should NOT call save_detections in that case,
    just leave analyzed_at NULL so the dashboard shows "pending" not "0").
    """
    if vision_result is None:
        return {"devices": None, "confidence": None,
                "needs_review": False, "reason": "vision unavailable"}

    for attempt in range(2):  # one retry on malformed output
        try:
            raw = _call_model(vision_result)
            parsed = json.loads(raw)

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
