import os

import pytest
from redis import Redis
from redis.exceptions import RedisError


def test_scheduler_cycle_skips_when_another_worker_holds_the_lease() -> None:
    redis_url = os.getenv("REDIS_URL")
    if redis_url is None:
        pytest.skip("REDIS_URL ist für den Redis-Integrationstest nicht gesetzt")

    with Redis.from_url(redis_url) as redis_client:
        try:
            redis_client.ping()
        except RedisError as error:
            pytest.skip(f"Redis ist für den Integrationstest nicht erreichbar: {error}")

    from lifepilot.scheduler import SCHEDULER_LOCK_KEY, run_scheduling_cycle

    with Redis.from_url(redis_url) as owner, Redis.from_url(redis_url) as contender:
        lease = owner.lock(SCHEDULER_LOCK_KEY, timeout=30)
        assert lease.acquire(blocking=False)
        try:
            acquired = run_scheduling_cycle(contender)
        finally:
            lease.release()

    assert acquired is False
