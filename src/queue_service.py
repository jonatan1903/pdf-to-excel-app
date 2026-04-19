import redis
from rq import Queue

from src import settings


redis_connection = redis.Redis.from_url(settings.REDIS_URL)
job_queue = Queue(
    settings.QUEUE_NAME,
    connection=redis_connection,
    default_timeout=settings.JOB_TIMEOUT_SECONDS,
)
