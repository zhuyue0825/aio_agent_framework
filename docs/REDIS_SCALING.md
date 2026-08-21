# Redis coordination and scaling

Status: implemented. Redis is coordination infrastructure; PostgreSQL remains the durable source of truth for users, conversations, messages, runs, proposed changes, and run events.

## What Redis does

- Agent runs are published to a Redis Stream and claimed through one consumer group. A successful delivery is acknowledged and removed only after the Java executor returns.
- Cancellation writes a ten-minute tombstone and publishes the run ID. Every Python instance receives the notification; an active model HTTP client is closed immediately.
- Java persists each run event in PostgreSQL, then publishes only its event ID. Other Java instances reload the authoritative row before broadcasting to their local SSE clients.
- Login/run rate limits and access-token revocation keys use Redis so they remain consistent across Java replicas.

## Delivery and restart behavior

1. Java commits a `PENDING` run in PostgreSQL before it publishes the Stream record.
2. A consumer changes the run to `RUNNING` in a transaction. Duplicate Stream deliveries become no-ops because only `PENDING` can enter execution.
3. On startup and every recovery sweep, Java republishes database `PENDING` runs.
4. A `RUNNING` run older than `AGENT_RECOVERY_STALE_AFTER` is terminated as `FAILED/RUN_INTERRUPTED`. The system does not silently claim that an interrupted model/tool call completed.
5. SSE reconnect uses `Last-Event-ID`; at most 500 newer persisted events are replayed, and duplicate Pub/Sub delivery is suppressed per subscriber.

This gives at-least-once queue delivery with database-level duplicate protection. It does not make a model/tool call transactional: a process can still stop after an external side effect but before recording success. Agent file changes therefore remain staged proposals and require a hash-checked user confirmation before the real workspace is written.

## Configuration

Both Compose files start password-protected Redis with AOF enabled. Required values:

```dotenv
REDIS_PASSWORD=replace-with-a-random-secret
AIO_REDIS_KEY_PREFIX=aio
```

Spring Boot enables distributed coordination with `AIO_REDIS_ENABLED=true`. FastAPI enables cancellation coordination whenever `REDIS_HOST` or `REDIS_URL` is present. Compose passes host, port, and password separately so random passwords do not need URL encoding.

## Operations

Prometheus exports local executor depth, Redis Stream depth, run outcomes, model request/token totals, and model/run latency. Alert rules cover a full executor queue, sustained Redis backlog, rising failures, and high model latency.

Useful checks:

```bash
docker compose exec redis redis-cli ping
docker compose exec redis redis-cli XLEN aio:agent-runs
curl --fail http://127.0.0.1:8081/actuator/prometheus | grep '^aio_agent_'
```

Changing `AIO_REDIS_KEY_PREFIX`, the Stream name, or consumer-group name on an existing deployment is a migration. Drain or explicitly account for records under the old key before changing it.
