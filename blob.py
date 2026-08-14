"""
Blob storage for event photos. Container: 'photos' (created by Protsahan,
azure-setup.md §2, with a 90-day lifecycle deletion rule already applied).
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

# How long a photo link stays valid. Long enough to cover a demo without
# leaving readable links scattered around for the rest of the day.
SAS_TTL_HOURS = 2


def upload_photo(device_id: str, session_id: str, sequence: int, photo_bytes: bytes) -> str:
    conn_str = os.environ["STORAGE_CONNECTION_STRING"]
    service = BlobServiceClient.from_connection_string(conn_str)
    container = service.get_container_client("photos")

    blob_name = f"{device_id}/{session_id}/{sequence:04d}-{uuid.uuid4().hex[:8]}.jpg"
    blob_client = container.get_blob_client(blob_name)
    blob_client.upload_blob(
        photo_bytes,
        overwrite=False,
        content_settings=ContentSettings(content_type="image/jpeg"),
    )
    return blob_client.url


def sas_url(blob_url: str) -> str:
    """Turn a stored blob URL into a time-limited, read-only link.

    The container is private and the storage account blocks anonymous access,
    so the bare URLs in count_event.photo_url return 409 in a browser and every
    <img> on the dashboard fails. The database keeps the plain URL as the stable
    identity of the photo; this adds a signature at read time.

    Read permission only, expiring in SAS_TTL_HOURS. Anyone who copies a link
    can view that one photo until it expires, and nothing else.
    """
    if not blob_url:
        return blob_url

    service = BlobServiceClient.from_connection_string(
        os.environ["STORAGE_CONNECTION_STRING"]
    )
    # Everything after the account host is "<container>/<blob name>", and the
    # blob name itself contains slashes (device/session/file.jpg).
    container, _, blob_name = urlparse(blob_url).path.lstrip("/").partition("/")
    if not blob_name:
        return blob_url

    token = generate_blob_sas(
        account_name=service.account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=service.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=SAS_TTL_HOURS),
    )
    return f"{blob_url}?{token}"


def with_photo_links(events):
    """Copy of `events` with each photo_url signed. Safe on missing photos."""
    signed = []
    for event in events:
        item = dict(event)
        if item.get("photo_url"):
            try:
                item["photo_url"] = sas_url(item["photo_url"])
            except Exception:
                # A signing failure must not blank the whole screen — the row
                # still carries its counts, which is what the totals need.
                pass
        signed.append(item)
    return signed
