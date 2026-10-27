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
