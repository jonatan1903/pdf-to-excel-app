import os


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("QUEUE_NAME", "pdf-jobs")
JOB_TIMEOUT_SECONDS = _get_int_env("JOB_TIMEOUT_SECONDS", 7200)
JOB_TTL_SECONDS = _get_int_env("JOB_TTL_SECONDS", 604800)

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
LOCAL_STORAGE_DIR = os.getenv("LOCAL_STORAGE_DIR", "./storage")

S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
