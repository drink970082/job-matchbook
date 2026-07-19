# syntax=docker/dockerfile:1.7

# node:20-alpine
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS base

# ---------- deps ----------
FROM base AS deps
RUN apk add --no-cache libc6-compat openssl
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# ---------- builder ----------
FROM base AS builder
RUN apk add --no-cache openssl
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The datasource is env("DATABASE_URL"); `prisma generate` validates that the
# var resolves, so provide a build-time value. The RUNTIME value is supplied by
# docker-compose (an absolute path on the shared volume) and takes precedence.
ENV DATABASE_URL="file:./applications.db"
RUN npx prisma generate
RUN npm run build

# ---------- runner ----------
FROM base AS runner
RUN apk add --no-cache openssl
WORKDIR /app

ENV NODE_ENV=production

# UID/GID match the host owner of the mounted db file so bind-mount writes
# work without chmod 777. Override at build time:
#   docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) ...
# match docker-compose default; host user is 1000
ARG UID=1000
ARG GID=1000

# Standalone Next.js output + static assets + public
COPY --from=builder --chown=${UID}:${GID} /app/.next/standalone ./
COPY --from=builder --chown=${UID}:${GID} /app/.next/static    ./.next/static
COPY --from=builder --chown=${UID}:${GID} /app/public          ./public

# Prisma schema only — the .db file is bind-mounted at runtime (see compose / run cmd).
# .dockerignore already excludes prisma/*.db and db/*.db from the build context.
COPY --from=builder --chown=${UID}:${GID} /app/prisma          ./prisma

# Run as numeric UID/GID directly — no need to create a named user.
# Docker accepts UID:GID even when the IDs don't exist in /etc/passwd.
USER ${UID}:${GID}

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# DATABASE_URL is injected at runtime by docker-compose, pointing at the
# directory-mounted shared volume (file:/data/applications.db) so WAL co-writing
# with the Python worker is safe. See docker-compose.yml.
CMD ["node", "server.js"]
