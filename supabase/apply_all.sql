-- ============================================================================
-- Apply ALL database migrations in one go (idempotent, safe to re-run).
--
-- How to run:
--   Supabase Dashboard -> SQL Editor -> paste this whole file -> Run.
--
-- This is the concatenation of every file in supabase/migrations, in order.
-- It exists so a database that was created from an older schema can be brought
-- up to date with a single paste. Every statement is idempotent.
-- ============================================================================

-- ============================================================================
-- 20261026_document_submissions.sql
-- ============================================================================

-- ============================================================================
-- Migration: staged post-approval document submissions
-- Date: 2026-10-26
--
-- Purpose:
--   Adds the staff-review / 3-attempt workflow for the Letter of Intent and
--   Notarized Scholarship Agreement, which are now uploaded after an
--   application is Approved instead of during the initial application.
--
-- How to run:
--   Supabase Dashboard -> SQL Editor -> paste this whole file -> Run.
--   Safe to run more than once (all statements are idempotent).
--
-- Tables added:
--   application_document_submissions - every upload attempt, one row each
--   application_document_allowances  - extra attempts granted by staff/admin
--
-- The existing application_documents table is kept: the latest submission for
-- each document is synced into it so the existing viewer/download links keep
-- working. Copy of Grades and Terminal report are untouched.
-- ============================================================================

create extension if not exists pgcrypto;

create table if not exists public.application_document_submissions (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications (id) on delete cascade,
  doc_key text not null check (doc_key in ('letterOfIntent', 'notarizedAgreement')),
  attempt_no integer not null check (attempt_no > 0),
  name text not null,
  path text not null unique,
  size_bytes bigint,
  mime_type text,
  uploaded_at timestamptz not null default now(),
  review_status text not null default 'Pending'
    check (review_status in ('Pending', 'Valid', 'Rejected')),
  review_reason text,
  reviewed_by text,
  reviewed_at timestamptz,
  unique (application_id, doc_key, attempt_no)
);

create index if not exists application_document_submissions_app_idx
  on public.application_document_submissions (application_id, doc_key, attempt_no desc);

create table if not exists public.application_document_allowances (
  application_id uuid not null references public.applications (id) on delete cascade,
  doc_key text not null check (doc_key in ('letterOfIntent', 'notarizedAgreement')),
  extra_attempts integer not null default 0 check (extra_attempts >= 0),
  updated_at timestamptz not null default now(),
  primary key (application_id, doc_key)
);

alter table public.application_document_submissions enable row level security;
alter table public.application_document_allowances enable row level security;

-- The API connects with the service role; anonymous and authenticated browser
-- roles must never touch these tables directly, matching the other tables.
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;


-- ============================================================================
-- 20261027_application_appeals.sql
-- ============================================================================

create extension if not exists pgcrypto;

create table if not exists public.application_appeals (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications (id) on delete cascade,
  reason text not null,
  status text not null default 'Pending' check (status in ('Pending', 'Accepted', 'Declined')),
  response text,
  responded_by text,
  created_at timestamptz not null default now(),
  responded_at timestamptz
);

create unique index if not exists application_appeals_application_idx
  on public.application_appeals (application_id);

alter table public.application_appeals enable row level security;

revoke all on table public.application_appeals from anon, authenticated;


-- ============================================================================
-- 20261027_audit_log.sql
-- ============================================================================

create table if not exists public.audit_log (
  id bigint generated always as identity primary key,
  actor_id uuid,
  actor_name text,
  actor_role text,
  action text not null,
  target_type text not null,
  target_id text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists audit_log_created_idx
  on public.audit_log (created_at desc, id desc);
create index if not exists audit_log_action_idx
  on public.audit_log (action);
create index if not exists audit_log_actor_idx
  on public.audit_log (actor_id);

alter table public.audit_log enable row level security;

revoke all on table public.audit_log from anon, authenticated;
revoke update, delete on table public.audit_log from public;


-- ============================================================================
-- 20261027_email_log.sql
-- ============================================================================

create table if not exists public.email_log (
  id bigint generated always as identity primary key,
  user_id uuid references public.users (id) on delete cascade,
  application_id uuid references public.applications (id) on delete cascade,
  subject text not null,
  status text not null check (status in ('sent', 'failed')),
  error text,
  created_at timestamptz not null default now()
);

alter table public.email_log enable row level security;

revoke all on table public.email_log from anon, authenticated;


-- ============================================================================
-- 20261027_rate_limits.sql
-- ============================================================================

create table if not exists public.rate_limits (
  scope text not null,
  bucket text not null,
  hits integer not null default 0,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  primary key (scope, bucket)
);

create index if not exists rate_limits_expires_idx
  on public.rate_limits (expires_at);

alter table public.rate_limits enable row level security;

revoke all on table public.rate_limits from anon, authenticated;


-- ============================================================================
-- 20261027_scholarship_deadline_at.sql
-- ============================================================================

alter table public.term_scholarships
  add column if not exists deadline_at timestamptz;


-- ============================================================================
-- 20261028_approval_roles.sql
-- ============================================================================

alter table public.users drop constraint if exists users_role_check;
alter table public.users
  add constraint users_role_check
  check (role in ('student', 'staff', 'admin', 'president', 'executive_president', 'super_admin'));


-- ============================================================================
-- 20261123_application_status_flow.sql
-- ============================================================================

-- ============================================================================
-- Migration: application approval status flow
-- Date: 2026-11-23
--
-- Purpose:
--   An application's status now records every approval level:
--   Submitted -> Under Evaluation -> Endorsed by Staff -> Approved by President
--   -> Approved by Executive President -> Exported (Rejected stays as-is).
--   "Approved" remains valid for applications saved before this change, and
--   students still only ever see Under Evaluation or the final Approved.
--
-- How to run:
--   Supabase Dashboard -> SQL Editor -> paste this whole file -> Run.
--   Safe to run more than once (the statements are idempotent).
--
-- Existing applications are not changed: their saved status keeps loading as-is.
-- ============================================================================

alter table public.applications drop constraint if exists applications_status_check;
alter table public.applications
  add constraint applications_status_check
  check (status in ('Submitted', 'Under Evaluation', 'Endorsed by Staff', 'Approved by President',
                    'Approved by Executive President', 'Approved', 'Exported', 'Rejected'));


-- ============================================================================
-- 20261123_past_discount.sql
-- ============================================================================

-- ============================================================================
-- Migration: past-term tuition fee discount at grade submission
-- Date: 2026-11-23
--
-- Purpose:
--   Students now declare the tuition fee discount they had in the past term or
--   academic year (25%, 50%, 75%, 100%, or not a scholar) when they submit
--   their Copy of Grades. The value is required before grades can be submitted.
--
-- How to run:
--   Supabase Dashboard -> SQL Editor -> paste this whole file -> Run.
--   Safe to run more than once (the statement is idempotent).
--
-- Existing applications are not changed: past_discount is null until the
-- student chooses a value on a new application.
-- ============================================================================

alter table public.applications
  add column if not exists past_discount integer
  check (past_discount in (25, 50, 75, 100));

