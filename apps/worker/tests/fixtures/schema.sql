-- Faithful copy of the Prisma-generated schema for the tables the worker
-- touches. Prisma OWNS the real schema (`prisma db push`); this file exists
-- ONLY so tests can spin up an equivalent in-memory/temp database. Keep in
-- sync with apps/web/prisma/schema.prisma.

CREATE TABLE "applications" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "company_name" TEXT NOT NULL,
    "job_title" TEXT NOT NULL,
    "application_url" TEXT,
    "date_applied" TEXT NOT NULL,
    "category" TEXT,
    "status" TEXT NOT NULL,
    "notes" TEXT,
    "last_updated" TEXT
);

CREATE TABLE "job_postings" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "source" TEXT NOT NULL,
    "external_id" TEXT NOT NULL,
    "company_slug" TEXT,
    "company_name" TEXT NOT NULL,
    "job_title" TEXT NOT NULL,
    "location" TEXT,
    "job_url" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "score" INTEGER,
    "score_detail" TEXT,
    "pipeline_status" TEXT NOT NULL DEFAULT 'new',
    "pipeline_error" TEXT,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "notify_attempts" INTEGER NOT NULL DEFAULT 0,
    "application_id" INTEGER,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT,
    "posted_at" TEXT,
    CONSTRAINT "job_postings_application_id_fkey" FOREIGN KEY ("application_id") REFERENCES "applications" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE "status_history" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "application_id" INTEGER NOT NULL,
    "status" TEXT NOT NULL,
    "timestamp" TEXT NOT NULL,
    CONSTRAINT "status_history_application_id_fkey" FOREIGN KEY ("application_id") REFERENCES "applications" ("id") ON DELETE CASCADE ON UPDATE NO ACTION
);

CREATE TABLE "watched_companies" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "source" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "recipe" TEXT,
    "created_at" TEXT NOT NULL
);

CREATE TABLE "feed_unresolved" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "feed" TEXT NOT NULL,
    "url" TEXT NOT NULL,
    "company_name" TEXT NOT NULL,
    "job_title" TEXT NOT NULL,
    "host" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT
);

CREATE TABLE "promotion_dismissed" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "source" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "created_at" TEXT NOT NULL
);

CREATE TABLE "app_settings" (
    "key" TEXT NOT NULL PRIMARY KEY,
    "value" TEXT NOT NULL,
    "updated_at" TEXT
);

CREATE INDEX "job_postings_pipeline_status_idx" ON "job_postings"("pipeline_status");
CREATE UNIQUE INDEX "job_postings_source_external_id_key" ON "job_postings"("source", "external_id");
CREATE UNIQUE INDEX "watched_companies_source_slug_key" ON "watched_companies"("source", "slug");
CREATE UNIQUE INDEX "feed_unresolved_url_key" ON "feed_unresolved"("url");
CREATE INDEX "feed_unresolved_reason_idx" ON "feed_unresolved"("reason");
CREATE INDEX "status_history_application_id_idx" ON "status_history"("application_id");
CREATE UNIQUE INDEX "promotion_dismissed_source_slug_key" ON "promotion_dismissed"("source", "slug");
