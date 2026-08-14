"""
Azure AI Vision (cv-baettledger, F0 free tier). REST call directly rather than
pulling in the full SDK — one endpoint, easy to keep in an Application Insights trace.
"""
import os
import logging
import requests

VISION_FEATURES = "objects,tags"


def analyze_image(photo_bytes: bytes) -> dict | None:
    """
    Returns the raw Vision result (objects + tags) or None if Vision is down /
    out of quota. api.md §6: on failure, log it and return None — the caller
    must still write a 200 and leave device_type NULL. Never raise.
    """
    endpoint = os.environ.get("VISION_ENDPOINT")
    key = os.environ.get("VISION_KEY")
    if not endpoint or not key:
        logging.warning("VISION not configured; skipping analysis")
        return None

    url = f"{endpoint.rstrip('/')}/vision/v3.2/analyze?visualFeatures={VISION_FEATURES}"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/octet-stream",
    }
    try:
        resp = requests.post(url, headers=headers, data=photo_bytes, timeout=15)
        if resp.status_code != 200:
            logging.warning("Vision returned %s: %s", resp.status_code, resp.text[:300])
            return None
        return resp.json()
    except requests.RequestException as e:
        logging.warning("Vision call failed: %s", e)
        return None
