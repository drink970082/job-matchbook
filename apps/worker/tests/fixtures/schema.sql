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
    "last_updated" TEXT,
    "actor" TEXT NOT NULL DEFAULT 'web'
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
    "score_detail" TEXT,
    "pipeline_status" TEXT NOT NULL DEFAULT 'new',
    "pipeline_error" TEXT,
    "application_id" INTEGER,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT,
    "posted_at" TEXT,
    "source_state" TEXT NOT NULL DEFAULT 'unknown',
    "source_last_seen_at" TEXT,
    "source_absent_count" INTEGER NOT NULL DEFAULT 0,
    "source_last_check_attempted_at" TEXT,
    "source_last_checked_at" TEXT,
    "source_last_check_outcome" TEXT NOT NULL DEFAULT 'not_checked',
    "source_last_check_error_category" TEXT,
    "source_content_hash" TEXT,
    "source_content_revision" INTEGER,
    "source_content_changed_at" TEXT,
    "verdict" TEXT NOT NULL DEFAULT 'pending',
    "verdict_at" TEXT,
    CONSTRAINT "job_postings_application_id_fkey" FOREIGN KEY ("application_id") REFERENCES "applications" ("id") ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE "job_screenings" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "job_posting_id" INTEGER NOT NULL,
    "state" TEXT NOT NULL,
    "result_json" TEXT,
    "error_category" TEXT,
    "error_message" TEXT,
    "backend" TEXT NOT NULL,
    "model" TEXT,
    "effort" TEXT,
    "evaluator_version" TEXT NOT NULL,
    "last_attempted_at" TEXT NOT NULL,
    "completed_at" TEXT,
    "source_content_revision" INTEGER,
    "profile_version" INTEGER,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT,
    CONSTRAINT "job_screenings_job_posting_id_fkey" FOREIGN KEY ("job_posting_id") REFERENCES "job_postings" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE "job_jev_assessments" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "job_posting_id" INTEGER NOT NULL,
    "state" TEXT NOT NULL,
    "verdict" TEXT,
    "reasons_json" TEXT,
    "result_json" TEXT,
    "error_category" TEXT,
    "model" TEXT,
    "policy_sha256" TEXT,
    "source_content_revision" INTEGER,
    "profile_version" INTEGER,
    "cost_usd" TEXT,
    "last_attempted_at" TEXT NOT NULL,
    "completed_at" TEXT,
    "created_at" TEXT NOT NULL,
    "updated_at" TEXT,
    CONSTRAINT "job_jev_assessments_job_posting_id_fkey" FOREIGN KEY ("job_posting_id") REFERENCES "job_postings" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE "job_triage_overrides" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "job_posting_id" INTEGER NOT NULL,
    "decision" TEXT NOT NULL,
    "reason" TEXT,
    "actor" TEXT NOT NULL,
    "source_content_revision" INTEGER,
    "created_at" TEXT NOT NULL,
    CONSTRAINT "job_triage_overrides_job_posting_id_fkey" FOREIGN KEY ("job_posting_id") REFERENCES "job_postings" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE "status_history" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "application_id" INTEGER NOT NULL,
    "status" TEXT NOT NULL,
    "timestamp" TEXT NOT NULL,
    "actor" TEXT NOT NULL DEFAULT 'web',
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

CREATE TABLE "audit_log" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "at" TEXT NOT NULL,
    "actor" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "entity" TEXT NOT NULL,
    "entity_id" INTEGER NOT NULL,
    "payload" TEXT NOT NULL
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

CREATE TABLE "app_settings" (
    "key" TEXT NOT NULL PRIMARY KEY,
    "value" TEXT NOT NULL,
    "updated_at" TEXT
);

CREATE TABLE "candidate_profile" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "title_include" TEXT NOT NULL DEFAULT '[]',
    "title_exclude" TEXT NOT NULL DEFAULT '[]',
    "max_age_days" INTEGER NOT NULL DEFAULT 0,
    "locations" TEXT NOT NULL DEFAULT '[]',
    "work_authorization" TEXT NOT NULL DEFAULT '',
    "security_clearance" TEXT NOT NULL DEFAULT '',
    "exclude_internships" BOOLEAN NOT NULL DEFAULT false,
    "exclude_contract" BOOLEAN NOT NULL DEFAULT false,
    "education" TEXT NOT NULL DEFAULT '[]',
    "experience" TEXT NOT NULL DEFAULT '[]',
    "target_roles" TEXT NOT NULL DEFAULT '[]',
    "open_to" TEXT NOT NULL DEFAULT '[]',
    "not_interested" TEXT NOT NULL DEFAULT '[]',
    "custom_packs" TEXT,
    "custom_triage_context" TEXT,
    "version" INTEGER NOT NULL DEFAULT 1,
    "actor" TEXT NOT NULL,
    "changed_at" TEXT,
    "confirmed_at" TEXT,
    "updated_at" TEXT NOT NULL
);

CREATE TABLE "worker_runs" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "started_at" TEXT NOT NULL,
    "finished_at" TEXT,
    "status" TEXT NOT NULL,
    "error_category" TEXT,
    "fetch_only" BOOLEAN NOT NULL DEFAULT false,
    "jev_enabled" BOOLEAN NOT NULL DEFAULT false,
    "config_json" TEXT NOT NULL,
    "counts_json" TEXT NOT NULL
);

CREATE INDEX "job_postings_pipeline_status_idx" ON "job_postings"("pipeline_status");
CREATE INDEX "job_postings_verdict_idx" ON "job_postings"("verdict");
CREATE INDEX "job_postings_source_source_last_check_attempted_at_idx" ON "job_postings"("source", "source_last_check_attempted_at");
CREATE UNIQUE INDEX "job_screenings_job_posting_id_key" ON "job_screenings"("job_posting_id");
CREATE UNIQUE INDEX "job_jev_assessments_job_posting_id_key" ON "job_jev_assessments"("job_posting_id");
CREATE UNIQUE INDEX "job_triage_overrides_job_posting_id_key" ON "job_triage_overrides"("job_posting_id");

CREATE INDEX "job_jev_assessments_state_last_attempted_at_idx" ON "job_jev_assessments"("state", "last_attempted_at");

CREATE INDEX "job_screenings_state_last_attempted_at_idx" ON "job_screenings"("state", "last_attempted_at");
CREATE UNIQUE INDEX "job_postings_source_external_id_key" ON "job_postings"("source", "external_id");
CREATE UNIQUE INDEX "watched_companies_source_slug_key" ON "watched_companies"("source", "slug");
CREATE INDEX "audit_log_entity_id_idx" ON "audit_log"("entity", "id");
CREATE UNIQUE INDEX "feed_unresolved_url_key" ON "feed_unresolved"("url");
CREATE INDEX "feed_unresolved_reason_idx" ON "feed_unresolved"("reason");
CREATE INDEX "status_history_application_id_idx" ON "status_history"("application_id");
CREATE INDEX "worker_runs_started_at_idx" ON "worker_runs"("started_at");
