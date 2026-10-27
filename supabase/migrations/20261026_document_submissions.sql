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
