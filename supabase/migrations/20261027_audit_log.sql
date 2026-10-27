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
