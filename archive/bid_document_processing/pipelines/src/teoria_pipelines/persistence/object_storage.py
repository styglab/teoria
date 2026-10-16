from __future__ import annotations

from typing import BinaryIO
from io import BytesIO
from urllib.parse import urlparse

from minio import Minio


class ObjectStorage:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str) -> None:
        parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
        self.bucket = bucket
        self.client = Minio(
            parsed.netloc or parsed.path,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
        )

    def put(self, object_key: str, stream: BinaryIO, length: int,
            content_type: str | None = None) -> None:
        stream.seek(0)
        self.client.put_object(
            self.bucket, object_key, stream, length,
            content_type=content_type or "application/octet-stream",
        )

    def get_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def put_bytes(self, object_key: str, value: bytes,
                  content_type: str = "application/octet-stream") -> None:
        self.put(object_key, BytesIO(value), len(value), content_type)

    def delete(self, object_key: str) -> None:
        self.client.remove_object(self.bucket, object_key)
