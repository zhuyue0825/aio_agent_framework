FROM python:3.12-slim

WORKDIR /app

RUN groupadd --gid 10001 aio \
    && useradd --uid 10001 --gid aio --create-home --shell /usr/sbin/nologin aio \
    && install -d -o aio -g aio -m 0700 /app/data /app/traces /workspaces

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY --chown=aio:aio agent_framework /app/agent_framework
COPY --chown=aio:aio backend /app/backend

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER aio
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
