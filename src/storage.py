import shutil
from pathlib import Path
from typing import Optional

import boto3

from src import settings


class StorageError(RuntimeError):
    pass


class StorageClient:
    def __init__(self):
        self.backend = settings.STORAGE_BACKEND
        self.s3_client = None
        self.bucket = ""

        if self.backend == "local":
            self.base_dir = Path(settings.LOCAL_STORAGE_DIR).resolve()
            self.base_dir.mkdir(parents=True, exist_ok=True)
            return

        if self.backend == "s3":
            if not settings.S3_BUCKET:
                raise StorageError("S3_BUCKET is required when STORAGE_BACKEND=s3")

            session = boto3.session.Session()
            client_kwargs = {
                "region_name": settings.S3_REGION or None,
                "endpoint_url": settings.S3_ENDPOINT_URL or None,
            }
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY

            self.s3_client = session.client("s3", **client_kwargs)
            self.bucket = settings.S3_BUCKET
            self.base_dir = None
            return

        raise StorageError(f"Unsupported STORAGE_BACKEND: {self.backend}")

    def _local_path(self, key: str) -> Path:
        normalized = key.replace("\\", "/").lstrip("/")
        return self.base_dir / normalized

    def upload_file(self, local_path: str, key: str, content_type: Optional[str] = None) -> None:
        if self.backend == "local":
            destination = self._local_path(key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, destination)
            return

        extra_args = {"ContentType": content_type} if content_type else None
        if extra_args:
            self.s3_client.upload_file(local_path, self.bucket, key, ExtraArgs=extra_args)
        else:
            self.s3_client.upload_file(local_path, self.bucket, key)

    def download_file(self, key: str, local_path: str) -> None:
        if self.backend == "local":
            source = self._local_path(key)
            if not source.exists():
                raise FileNotFoundError(f"Storage key not found: {key}")
            destination = Path(local_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return

        self.s3_client.download_file(self.bucket, key, local_path)

    def delete_key(self, key: str) -> None:
        if self.backend == "local":
            target = self._local_path(key)
            if target.exists():
                target.unlink()
            return

        self.s3_client.delete_object(Bucket=self.bucket, Key=key)


storage_client = StorageClient()
