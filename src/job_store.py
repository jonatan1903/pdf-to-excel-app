from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src import settings
from src.queue_service import redis_connection


JOB_KEY_PREFIX = "pdf_to_excel:job:"


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_string(value: Any) -> str:
    return "" if value is None else str(value)


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def create_job(
    job_id: str,
    *,
    original_filename: str,
    output_filename: str,
    input_key: str,
    output_key: str,
) -> Dict[str, Any]:
    now = _now_iso()
    payload = {
        "job_id": job_id,
        "status": "queued",
        "original_filename": original_filename,
        "output_filename": output_filename,
        "input_key": input_key,
        "output_key": output_key,
        "error": "",
        "created_at": now,
        "updated_at": now,
        "total_cases": "",
        "valid_cases": "",
        "error_cases": "",
    }
    redis_connection.hset(_job_key(job_id), mapping=payload)
    redis_connection.expire(_job_key(job_id), settings.JOB_TTL_SECONDS)
    return payload


def update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    serialized = {key: _to_string(value) for key, value in fields.items()}
    redis_connection.hset(_job_key(job_id), mapping=serialized)
    redis_connection.expire(_job_key(job_id), settings.JOB_TTL_SECONDS)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    raw = redis_connection.hgetall(_job_key(job_id))
    if not raw:
        return None

    payload: Dict[str, Any] = {}
    for key, value in raw.items():
        payload[_decode(key)] = _decode(value)

    for field in ("total_cases", "valid_cases", "error_cases"):
        value = payload.get(field)
        if value in (None, ""):
            payload[field] = None
            continue
        try:
            payload[field] = int(value)
        except ValueError:
            payload[field] = None

    return payload
