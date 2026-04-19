import logging

from rq import Worker

from src import settings
from src.queue_service import redis_connection


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


if __name__ == "__main__":
    worker = Worker([settings.QUEUE_NAME], connection=redis_connection)
    worker.work()
