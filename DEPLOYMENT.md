# Production deployment

The production Compose stack publishes only Nginx on TCP `443`. PostgreSQL, Sandbox, FastAPI, and Spring Boot stay on the private Compose network.

## 1. Prepare secrets and directories

```bash
cp .env.example .env
chmod 600 .env
mkdir -p workspaces deploy/certs
```

Fill every required blank value in `.env`. Generate independent random values, for example with `openssl rand -base64 48`. Keep `AIO_PUBLIC_REGISTRATION_ENABLED=false` for an Internet-facing deployment.

If the PostgreSQL volume already existed with an older password, recreate only PostgreSQL with the new environment and rotate the database role before starting the other services:

```bash
docker compose -f docker-compose.prod.yml up -d --no-deps --force-recreate postgres
docker compose -f docker-compose.prod.yml exec -T postgres sh -eu -c 'psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=role_name="$POSTGRES_USER" --set=role_password="$POSTGRES_PASSWORD" --file=/opt/aio/rotate-password.sql'
```

On a Linux server, the Python container runs as uid/gid `10001`; make the configured workspace writable by that account:

```bash
sudo chown -R 10001:10001 workspaces
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

Test restore procedures periodically. A backup that has never been restored is not yet a verified recovery plan.

The backup volume is still on the same server as PostgreSQL. Copy encrypted backups to separate storage if server or disk loss must be recoverable.

## 4. Logs

Nginx, Spring Boot, FastAPI, and the backup job write one JSON object per line. Use the returned `trace_id` to follow one request across services:

```bash
docker compose -f docker-compose.prod.yml logs --since 30m | grep 'the-trace-id'
```

`DOCKER_LOG_MAX_SIZE` and `DOCKER_LOG_MAX_FILES` limit each container's local `json-file` logs. Forward logs to separate storage before relying on them for audits or long-term history.

## 5. Updating

```bash
git pull --ff-only
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker compose -f docker-compose.prod.yml ps
```

Never expose ports `5432`, `8000`, `8080`, or `8081` in a public firewall rule.
