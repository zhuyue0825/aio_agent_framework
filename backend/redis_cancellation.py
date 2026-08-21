from __future__ import annotations

import logging
import os
from threading import Event, Thread
from typing import Callable
from uuid import UUID

import redis


logger = logging.getLogger("aio_agent.redis_cancellation")


class RedisCancellationBridge:
    def __init__(self, cancel_local: Callable[[UUID], bool]) -> None:
        self.url = os.environ.get("REDIS_URL", "").strip()
        self.host = os.environ.get("REDIS_HOST", "").strip()
        self.port = int(os.environ.get("REDIS_PORT", "6379"))
        self.password = os.environ.get("REDIS_PASSWORD") or None
        self.prefix = os.environ.get("AIO_REDIS_KEY_PREFIX", "aio").strip() or "aio"
        self.cancel_local = cancel_local
        self.client: redis.Redis | None = None
        self._thread: Thread | None = None
        self._stopped = Event()

    @property
    def enabled(self) -> bool:
        return bool(self.url or self.host)

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        connection_options = {
            "decode_responses": True,
            "socket_connect_timeout": 2,
            "socket_timeout": 2,
            "health_check_interval": 30,
        }
        if self.url:
            self.client = redis.Redis.from_url(self.url, **connection_options)
        else:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                **connection_options,
            )
        self.client.ping()
        self._thread = Thread(target=self._listen, name="redis-run-cancellation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self.client is not None:
            self.client.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def publish(self, run_id: UUID) -> None:
        if self.client is None:
            return
        try:
            pipeline = self.client.pipeline()
            pipeline.setex(self._key(run_id), 600, "1")
            pipeline.publish(self._channel(), str(run_id))
            pipeline.execute()
        except redis.RedisError:
            logger.warning("redis_cancel_publish_failed", extra={"run_id": str(run_id)}, exc_info=True)

    def was_cancelled(self, run_id: UUID) -> bool:
        if self.client is None:
            return False
        try:
            return bool(self.client.exists(self._key(run_id)))
        except redis.RedisError:
            logger.warning("redis_cancel_check_failed", extra={"run_id": str(run_id)}, exc_info=True)
            return False

    def _listen(self) -> None:
        assert self.client is not None
        while not self._stopped.is_set():
            try:
                with self.client.pubsub(ignore_subscribe_messages=True) as subscriber:
                    subscriber.subscribe(self._channel())
                    while not self._stopped.is_set():
                        message = subscriber.get_message(timeout=1)
                        if not message or message.get("type") != "message":
                            continue
                        try:
                            self.cancel_local(UUID(str(message.get("data"))))
                        except (TypeError, ValueError):
                            logger.debug("ignored_invalid_cancel_message")
            except redis.RedisError:
                if self._stopped.wait(1):
                    return
                logger.warning("redis_cancel_listener_reconnecting", exc_info=True)

    def _channel(self) -> str:
        return f"{self.prefix}:run-cancel"

    def _key(self, run_id: UUID) -> str:
        return f"{self.prefix}:run-cancelled:{run_id}"
