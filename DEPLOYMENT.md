# Production deployment

The production Compose stack publishes only Nginx on TCP `443`. PostgreSQL, Sandbox, FastAPI, and Spring Boot stay on the private Compose network.

## 1. Prepare secrets and directories

```bash
cp .env.example .env
chmod 600 .env
mkdir -p workspaces deploy/certs
```

Fill every required blank value in `.env`, including independent PostgreSQL and Redis passwords. Generate independent random values, for example with `openssl rand -base64 48`. Keep `AIO_PUBLIC_REGISTRATION_ENABLED=false` and `AIO_ENABLE_LOCAL_TEST_TOOL=false` for an Internet-facing deployment.

Keep `MODEL_REMOTE_ALLOWED_HOSTS` and `MODEL_LOCAL_ALLOWED_HOSTS` narrow. The administrator UI can only save model endpoints whose host is on the corresponding list; this is the SSRF boundary, not a convenience setting.

Remote API deployment does not start MiniMind. To use the local model in production, place
`full_sft_768.pth` below `MINIMIND_WEIGHTS_HOST_PATH` and enable the opt-in profile:

```bash
docker compose -f docker-compose.prod.yml --profile local-model up -d --build
docker compose -f docker-compose.prod.yml --profile local-model ps
```

The Agent reaches it only through the private Compose address `http://minimind:8998/v1`;
the production stack does not publish port `8998` on the host.

If the PostgreSQL volume already existed with an older password, recreate only PostgreSQL with the new environment and rotate the database role before starting the other services:

```bash
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate postgres
docker compose -f docker-compose.prod.yml exec -T postgres sh -eu -c 'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=role_name="$POSTGRES_USER" --set=role_password="$POSTGRES_PASSWORD" --file=/opt/aio/rotate-password.sql'
```

On a Linux server, the Python container runs as uid/gid `10001`; make the configured workspace writable by that account:

```bash
sudo chown -R 10001:10001 workspaces
```

Production workspaces are tenant-scoped. The Python service creates `/workspaces/<user-uuid>` for each account and refuses to open another user's directory. After creating an account, obtain its UUID from `GET /api/v1/auth/me`, then copy/clone only that user's projects below the matching host directory:

```text
workspaces/<user-uuid>/<project-name>
```

Put the certificate chain and private key at:

```text
deploy/certs/fullchain.pem
deploy/certs/privkey.pem
```

## 2. Start and verify

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl --fail --insecure https://127.0.0.1/healthz
```

Use a certificate issued for the real domain in normal browser access. The `--insecure` flag above is only for a local server-side health check where the certificate hostname does not match `127.0.0.1`.

Redis uses AOF for coordination recovery, but PostgreSQL remains authoritative. Check both health endpoints before allowing traffic:

```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
docker compose -f docker-compose.prod.yml exec postgres pg_isready
```

## 3. Backups and restore

`postgres-backup` immediately creates a custom-format dump, then repeats every `POSTGRES_BACKUP_INTERVAL_SECONDS`. Old dumps are removed after `POSTGRES_BACKUP_RETENTION_DAYS`.

List backup files:

```bash
docker compose -f docker-compose.prod.yml exec postgres-backup ls -lh /backups
```

Copy one backup to the host and restore it into an empty database:

```bash
docker compose -f docker-compose.prod.yml cp postgres-backup:/backups/aio_agent_YYYYMMDDTHHMMSSZ.dump ./aio_agent.dump
docker compose -f docker-compose.prod.yml cp ./aio_agent.dump postgres:/tmp/aio_agent.dump
docker compose -f docker-compose.prod.yml exec postgres sh -eu -c 'pg_restore --clean --if-exists --no-owner --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" /tmp/aio_agent.dump'
```

Run the non-destructive restore drill periodically. It restores the latest dump into a temporary database whose name must end in `_restore_drill`, verifies Flyway history and users, then deletes only that temporary database:

```bash
docker compose -f docker-compose.prod.yml exec postgres-backup postgres-restore-drill
```

A backup that has never passed this drill is not yet a verified recovery plan.

The backup volume is still on the same server as PostgreSQL. To sync it to a separately administered location, configure an rclone remote (prefer an encrypted `crypt` remote) in the Git-ignored `deploy/rclone.conf`, set `POSTGRES_BACKUP_REMOTE`, then start the profile:

```bash
docker compose -f docker-compose.prod.yml --profile offsite-backup up -d backup-offsite
```

Verify the remote object count and perform a restore drill from a downloaded off-site dump; a successful local copy alone does not prove off-site recovery.

## 4. Logs

Nginx, Spring Boot, FastAPI, and the backup job write one JSON object per line. Use the returned `trace_id` to follow one request across services:

```bash
docker compose -f docker-compose.prod.yml logs --since 30m | grep 'the-trace-id'
```

`DOCKER_LOG_MAX_SIZE` and `DOCKER_LOG_MAX_FILES` limit each container's local `json-file` logs. Forward logs to separate storage before relying on them for audits or long-term history.

## 5. Metrics and alerts

Create a Git-ignored file containing one HTTPS receiver URL, with no trailing comments:

```bash
printf '%s\n' 'https://your-alert-receiver.example/webhook' > deploy/alert-webhook-url
chmod 600 deploy/alert-webhook-url
```

Then start Prometheus and Alertmanager on loopback-only ports:

```bash
docker compose -f docker-compose.prod.yml --profile observability up -d prometheus alertmanager
curl --fail http://127.0.0.1:9090/-/healthy
curl --fail http://127.0.0.1:9093/-/healthy
```

Rules cover service availability, executor/Redis queue backlog, rising failed runs, and model latency. Test the receiver and a real firing/resolved notification before treating alerting as operational.

## 6. Updating

```bash
git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker compose -f docker-compose.prod.yml ps
```

Never expose ports `5432`, `6379`, `8000`, `8080`, `8081`, `9090`, or `9093` in a public firewall rule.
