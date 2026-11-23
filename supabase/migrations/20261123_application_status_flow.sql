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
