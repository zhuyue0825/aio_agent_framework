# Redis scaling decision

Status: deferred until the application is deployed with more than one Java or Python instance.

The current deployment intentionally runs one Spring Boot instance and one FastAPI worker. PostgreSQL is already the durable source of truth for runs and run events, so adding an otherwise unused Redis container would increase operations work without fixing horizontal scaling by itself.

Redis becomes justified when at least one of these is true:

- Spring Boot or FastAPI is scaled to two or more instances.
- queued Agent jobs must survive a Java process restart and be claimed by independent workers.
- cancellation must be visible to every Python worker.
- an SSE subscriber may connect to a different Java instance from the one receiving progress callbacks.

At that point, implement Redis as a coordinated change rather than only adding a container:

1. Replace the in-process `@Async` dispatch with a durable queue such as Redis Streams and a consumer group. Keep the database idempotency key as the final duplicate-execution guard.
2. Store short-lived cancellation tombstones as `run:{id}:cancelled` keys with TTL, and check them between model/tool steps.
3. Publish persisted run-event IDs through Redis Pub/Sub or Streams. Each Java instance then reloads the authoritative event from PostgreSQL before broadcasting it to local SSE emitters.
4. Add queue depth, oldest-job age, consumer lag, retry/dead-letter counts, and Redis health metrics before enabling multiple replicas.

Redis must remain disposable coordination infrastructure; PostgreSQL continues to own users, conversations, runs, and event history.
