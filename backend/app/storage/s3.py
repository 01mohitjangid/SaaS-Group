"""S3-compatible implementation — this is the Cloudflare R2 path.

R2 speaks the S3 API, so the *only* difference between R2, MinIO and AWS S3 is the
endpoint URL and the credentials. Moving production from local disk to R2 is a
config change (``STORAGE_BACKEND=s3`` plus the ``S3_*`` variables), not a code
change; see the README.

``put_object`` is atomic for a single key in every S3-compatible store, so the
publish job's pointer flip keeps its guarantee here.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.storage.base import ObjectNotFound, StoredObject, validate_key

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

_MISSING = ("404", "NoSuchKey", "NotFound")


class S3CompatibleStorage:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "auto",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._public_base_url = (public_base_url or "").rstrip("/")
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            # R2 does not support the newer streaming checksum headers.
            config=Config(
                signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}
            ),
        )

    def _put_sync(self, key: str, data: bytes, content_type: str) -> str | None:
        response = self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )
        etag = response.get("ETag")
        return str(etag) if etag is not None else None

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        validate_key(key)
        etag = await asyncio.to_thread(self._put_sync, key, data, content_type)
        return StoredObject(key=key, size=len(data), content_type=content_type, etag=etag)

    def _get_sync(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                raise ObjectNotFound(key) from exc
            raise
        body: bytes = response["Body"].read()
        return body

    async def get(self, key: str) -> bytes:
        validate_key(key)
        return await asyncio.to_thread(self._get_sync, key)

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(lambda: self._client.delete_object(Bucket=self._bucket, Key=key))

    def _exists_sync(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                return False
            raise
        return True

    async def exists(self, key: str) -> bool:
        validate_key(key)
        return await asyncio.to_thread(self._exists_sync, key)

    def url_for(self, key: str) -> str:
        validate_key(key)
        if self._public_base_url:
            return f"{self._public_base_url}/{key}"
        # No public bucket domain configured — fall back to a short-lived signed URL.
        url: str = self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=3600
        )
        return url
