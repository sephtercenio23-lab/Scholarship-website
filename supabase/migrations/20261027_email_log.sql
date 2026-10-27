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
