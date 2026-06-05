# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

# UID/GID match the host owner of the shared ../db and ../resumes mounts so the
# worker can CO-WRITE the SQLite db (incl. WAL -wal/-shm sidecars) with the
# Next.js container, and the web app can read the PDFs it writes.
ARG UID=1000
ARG GID=1000

# Pinned tectonic (single static musl binary — no full texlive needed).
ARG TECTONIC_VERSION=0.15.0

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Tectonic caches its package bundle here; we prewarm it at build time so the
    # first real compile doesn't hang downloading from CTAN at runtime.
    TECTONIC_CACHE_DIR=/opt/tectonic-cache

WORKDIR /app

# Runtime libs for tectonic's font handling + TLS for the bundle fetch.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Install the tectonic binary.
RUN curl -fsSL \
      "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
      -o /tmp/tectonic.tar.gz \
    && tar -xzf /tmp/tectonic.tar.gz -C /usr/local/bin tectonic \
    && rm /tmp/tectonic.tar.gz \
    && tectonic --version

# Python deps.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Prewarm the tectonic bundle: compile a trivial doc so the (large) default
# bundle is downloaded into TECTONIC_CACHE_DIR and baked into this image layer.
# Make the cache writable by the runtime UID so a JD needing an extra package can
# still extend it at runtime.
RUN mkdir -p /tmp/warm \
    && printf '\\documentclass{article}\\begin{document}warm\\end{document}\n' > /tmp/warm/w.tex \
    && tectonic --outdir /tmp/warm /tmp/warm/w.tex \
    && rm -rf /tmp/warm \
    && chown -R ${UID}:${GID} ${TECTONIC_CACHE_DIR}

# Application code (config.yaml, resume/, .env are mounted at runtime, not baked).
COPY ats_worker ./ats_worker

USER ${UID}:${GID}

# Default: run the scheduler (fetch→score→tailor→notify on config's interval,
# plus one immediate pass). Override with `--once` for a single test pass.
CMD ["python", "-m", "ats_worker.run", "--config", "/app/config.yaml", "--env", "/app/.env"]
