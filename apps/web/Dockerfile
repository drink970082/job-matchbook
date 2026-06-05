# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS base

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
ARG UID=1001
ARG GID=1001

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
