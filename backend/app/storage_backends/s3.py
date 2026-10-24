"""
Module: storage_backends.s3

S3-compatible file storage backend (I-M-10), using boto3's S3 client. Works
against the bundled docker-compose `storage` service (SeaweedFS) or real AWS
S3 by pointing `endpoint_url` at either. This is the concrete second backend
that proves the storage abstraction genuinely supports "different backends",
not just local disk.
"""

from __future__ import annotations

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class S3CompatibleFileStorageBackend:
    """Stores files as objects in an S3-compatible bucket."""

    name = "s3"

    def __init__(self, bucket: str, endpoint_url: str, access_key: str, secret_key: str, region: str, create_bucket: bool = True) -> None:
        """Connects to the bucket.

        Args:
            bucket: Bucket name.
            endpoint_url: S3 endpoint.
            access_key / secret_key / region: Credentials and region.
            create_bucket: Create the bucket if it is missing (the application's own behaviour). A read-only
                client, such as the backup tool's, passes False: it must never create anything.
        """
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )
        if create_bucket:
            self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Creates the configured bucket if it doesn't already exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def save(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def read(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise FileNotFoundError(key) from exc
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        """Whether an object is stored under `key` (a HEAD request, no body transferred).

        Raises:
            ClientError: On any failure other than "not found" (a denied or unreachable store is not "absent").
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True
