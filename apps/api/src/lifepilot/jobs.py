import logging

from redis import Redis
from rq import Queue, Worker

from lifepilot.config import settings
from lifepilot.scheduler import SCHEDULE_QUEUE_NAME

logger = logging.getLogger(__name__)


def run_worker() -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL muss für den Job-Worker gesetzt sein")
    redis_client = Redis.from_url(settings.redis_url)
    queue = Queue(SCHEDULE_QUEUE_NAME, connection=redis_client)
    logger.info("LifePilot-Worker hört auf der Queue %s", SCHEDULE_QUEUE_NAME)
    try:
        Worker([queue], connection=redis_client).work(with_scheduler=True)
    finally:
        redis_client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
