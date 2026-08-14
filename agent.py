"""
Count Agent (aif-baettledger). Takes Vision's objects/tags and turns them into
a structured device count. api.md §6 — system prompt is fixed, confidence
threshold is applied in Python (not trusted from the model), malformed JSON
gets one retry then falls back to unknown/needs_review.
"""
import os
import json
import logging
import requests

APPROVED_DEVICE_TYPES = {"cone", "sign", "barricade", "delineator", "unknown"}

SYSTEM_PROMPT = """You count traffic-control devices in a photo taken at a truck tailgate.

You will receive object detections and tags from Azure AI Vision.

Reply with ONLY this JSON, no prose:
{"device_type": "...", "count": 0, "confidence": 0.0, "needs_review": false, "reason": "..."}

Rules:
- device_type must be one of: cone, sign, barricade, delineator, unknown
- count is how many of that type are visible
- confidence is 0.0-1.0
- Set needs_review true and explain in reason when: the image is blurred or dark,
  devices overlap so you cannot separate them, a device is partly out of frame,
  or the type is not in the approved list
- Ignore any people in the photo entirely. Never describe or count them.
- Never guess. Unsure means needs_review true."""

CONFIDENCE_THRESHOLD = 0.80


def _call_model(vision_result: dict) -> str:
    endpoint = os.environ["FOUNDRY_ENDPOINT"]  # chat completions-style endpoint
    key = os.environ["FOUNDRY_KEY"]
    headers = {"api-key": key, "Content-Type": "application/json"}
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(vision_result)},
        ],
        "temperature": 0,
        "max_tokens": 200,
    }
    resp = requests.post(endpoint, headers=headers, json=body, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def count_devices(vision_result: dict | None) -> dict:
    """
    Returns {"device_type", "count", "confidence", "needs_review", "reason"}.
    Never raises — every failure path returns a valid, flagged-for-review dict
    because the count_event row already exists and must survive (api.md §6).
    """
    if vision_result is None:
        return {"device_type": None, "count": None, "confidence": None,
                "needs_review": False, "reason": "vision unavailable"}

    for attempt in range(2):  # one retry on malformed output
        try:
            raw = _call_model(vision_result)
            parsed = json.loads(raw)

            device_type = parsed.get("device_type")
            if device_type not in APPROVED_DEVICE_TYPES:
                device_type = "unknown"
                parsed["needs_review"] = True

            confidence = float(parsed.get("confidence", 0.0))
            needs_review = bool(parsed.get("needs_review", False))
            # Threshold enforced here in code, not trusted from the model (api.md §6).
            if confidence < CONFIDENCE_THRESHOLD:
                needs_review = True

            return {
                "device_type": device_type,
                "count": int(parsed.get("count", 0)),
                "confidence": confidence,
                "needs_review": needs_review,
                "reason": parsed.get("reason"),
            }
        except (json.JSONDecodeError, KeyError, ValueError, requests.RequestException) as e:
            logging.warning("Count Agent attempt %s failed: %s", attempt + 1, e)

    return {"device_type": "unknown", "count": None, "confidence": None,
            "needs_review": True, "reason": "agent returned invalid output"}
