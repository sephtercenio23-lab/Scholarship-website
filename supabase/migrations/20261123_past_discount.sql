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
