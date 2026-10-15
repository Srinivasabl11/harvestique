FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/backend

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Apply migrations (additive only; never drops data) then start the API. Hosting platforms set $PORT (Render: 10000);
# local Docker Compose uses 8000. --proxy-headers: behind an HTTPS proxy, per-client limits need the real client IP.
# --no-access-log: the app logs each request itself (route template, status, time, request id), without the query
# strings and client addresses uvicorn's access log would add.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
