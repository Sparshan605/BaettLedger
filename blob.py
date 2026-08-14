"""
Blob storage for event photos. Container: 'photos' (created by Protsahan,
azure-setup.md §2, with a 90-day lifecycle deletion rule already applied).
"""
import os
import uuid
from azure.storage.blob import BlobServiceClient, ContentSettings


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
