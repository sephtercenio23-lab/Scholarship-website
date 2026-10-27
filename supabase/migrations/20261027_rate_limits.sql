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
