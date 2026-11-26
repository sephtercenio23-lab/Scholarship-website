-- ============================================================================
-- Migration: finance hand-off, re-approval flag, immutable audit log
-- Date: 2026-11-26
--
-- Purpose:
--   * New terminal status "Sent to Finance": after the Authorized Staff, President
--     and Executive President approvals, the approved scholars are emailed to
--     Finance automatically in Excel format. "Exported" stays valid for records
--     created before this change.
--   * changed_after_finance marks an application that was edited after Finance
--     already received it. Such an application goes through the three approvals
--     again and its correction list is emailed to Finance after the last approval.
--   * finance_sent_at records when the scholar/correction list reached Finance.
--   * audit_log becomes append-only: a trigger rejects UPDATE and DELETE so the
--     approval, export and finance-send history cannot be edited.
--
-- How to run:
--   Supabase Dashboard -> SQL Editor -> paste this whole file -> Run.
--   Safe to run more than once (the statements are idempotent).
-- ============================================================================

alter table public.applications drop constraint if exists applications_status_check;
alter table public.applications
  add constraint applications_status_check
  check (status in ('Submitted', 'Under Evaluation', 'Endorsed by Staff', 'Approved by President',
                    'Approved by Executive President', 'Sent to Finance', 'Approved', 'Exported',
                    'Rejected'));

alter table public.applications
  add column if not exists changed_after_finance boolean not null default false;
alter table public.applications
  add column if not exists finance_sent_at timestamptz;

create index if not exists applications_finance_sent_idx
  on public.applications (finance_sent_at) where finance_sent_at is not null;
create index if not exists applications_changed_after_finance_idx
  on public.applications (changed_after_finance) where changed_after_finance;

create or replace function public.reject_audit_log_change()
returns trigger
language plpgsql
as $$
begin
  raise exception 'The audit log is append-only and cannot be edited or deleted.';
end;
$$;

drop trigger if exists audit_log_append_only on public.audit_log;
create trigger audit_log_append_only
  before update or delete on public.audit_log
  for each row execute function public.reject_audit_log_change();

revoke update, delete, truncate on public.audit_log from public;
revoke all on table public.audit_log from anon, authenticated;
