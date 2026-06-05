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
    "company_name" TEXT NOT NULL,
    "job_title" TEXT NOT NULL,
    "location" TEXT,
    "job_url" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "score" INTEGER,
    "score_detail" TEXT,
    "resume_tex" TEXT,
    "resume_path" TEXT,
    "resume_pages" INTEGER,
    "pipeline_status" TEXT NOT NULL DEFAULT 'new',
    "pipeline_error" TEXT,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "application_id" INTEGER,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT,
    CONSTRAINT "job_postings_application_id_fkey" FOREIGN KEY ("application_id") REFERENCES "applications" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE INDEX "job_postings_pipeline_status_idx" ON "job_postings"("pipeline_status");
CREATE UNIQUE INDEX "job_postings_source_external_id_key" ON "job_postings"("source", "external_id");
