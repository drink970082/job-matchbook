# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

# UID/GID match the host owner of the shared ../db mount so the worker can
# CO-WRITE the SQLite db (incl. WAL -wal/-shm sidecars) with the Next.js container.
ARG UID=1000
ARG GID=1000

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Python deps.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Application code (config.yaml, resume/, .env are mounted at runtime, not baked).
COPY ats_worker ./ats_worker

USER ${UID}:${GID}

# Default: run the scheduler (fetch→score→notify on config's interval, plus one
# immediate pass). Override with `--once` for a single test pass.
CMD ["python", "-m", "ats_worker.run", "--config", "/app/config.yaml", "--env", "/app/.env"]
