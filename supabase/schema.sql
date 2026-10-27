create extension if not exists pgcrypto;

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  full_name text not null,
  email text not null,
  password_hash text not null,
  role text not null check (role in ('student', 'staff', 'admin')),
  student_id text,
  program text,
  year_level text,
  token_version integer not null default 0,
  failed_attempts integer not null default 0,
  locked_until timestamptz,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists users_email_active_idx
  on public.users (lower(email)) where deleted_at is null;
create unique index if not exists users_student_id_active_idx
  on public.users (student_id) where deleted_at is null and student_id is not null;
create index if not exists users_role_idx
  on public.users (role) where deleted_at is null;

create table if not exists public.academic_terms (
  id uuid primary key default gen_random_uuid(),
  trimester text not null check (trimester in ('1st Trimester', '2nd Trimester', '3rd Trimester')),
  academic_year text not null,
  is_current boolean not null default false,
  created_at timestamptz not null default now(),
  unique (trimester, academic_year)
);

create unique index if not exists academic_terms_current_idx
  on public.academic_terms (is_current) where is_current;

create table if not exists public.term_scholarships (
  term_id uuid not null references public.academic_terms (id) on delete cascade,
  scholarship_key text not null,
  status text not null default 'Open' check (status in ('Open', 'Closed')),
  benefit text not null,
  deadline text not null,
  deadline_at timestamptz,
  eligibility text[] not null default '{}',
  sort_order integer not null default 0,
  primary key (term_id, scholarship_key)
);

create sequence if not exists public.application_code_seq start 1;

create table if not exists public.applications (
  id uuid primary key,
  code text not null unique,
  student_id uuid not null references public.users (id),
  term_id uuid not null references public.academic_terms (id),
  scholarship_type text not null,
  program text not null,
  year_level text not null,
  gwa numeric(5, 2),
  lowest_grade numeric(5, 2),
  has_failing_grade boolean not null default false,
  has_incomplete_grade boolean not null default false,
  has_dropped_grade boolean not null default false,
  status text not null default 'Submitted'
    check (status in ('Submitted', 'Under Evaluation', 'Approved', 'Rejected')),
  remarks text,
  evaluated_by text,
  discount_percent integer check (discount_percent between 0 and 100),
  duty_hours integer not null default 0 check (duty_hours between 0 and 80),
  duty_completed boolean not null default false,
  report_received_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists applications_one_per_type_idx
  on public.applications (student_id, term_id, scholarship_type) where deleted_at is null;
create index if not exists applications_term_idx on public.applications (term_id);
create index if not exists applications_student_idx on public.applications (student_id);
create index if not exists applications_status_idx on public.applications (status);

create table if not exists public.application_documents (
  application_id uuid not null references public.applications (id) on delete cascade,
  doc_key text not null check (doc_key in ('copyOfGrades', 'letterOfIntent', 'notarizedAgreement', 'terminalReport')),
  name text not null,
  path text not null unique,
  size_bytes bigint,
  mime_type text,
  uploaded_at timestamptz not null default now(),
  primary key (application_id, doc_key)
);

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

create table if not exists public.application_history (
  id bigint generated always as identity primary key,
  application_id uuid not null references public.applications (id) on delete cascade,
  status text not null,
  event_type text not null default 'status_changed',
  actor_name text,
  remarks text,
  created_at timestamptz not null default now()
);

create index if not exists application_history_app_idx
  on public.application_history (application_id, created_at, id);

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users (id) on delete cascade,
  application_id uuid references public.applications (id) on delete set null,
  message text not null,
  type text not null default 'student',
  is_read boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists notifications_user_idx
  on public.notifications (user_id, is_read, created_at desc);

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

create table if not exists public.email_log (
  id bigint generated always as identity primary key,
  user_id uuid references public.users (id) on delete cascade,
  application_id uuid references public.applications (id) on delete cascade,
  subject text not null,
  status text not null check (status in ('sent', 'failed')),
  error text,
  created_at timestamptz not null default now()
);

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

alter table public.users enable row level security;
alter table public.academic_terms enable row level security;
alter table public.term_scholarships enable row level security;
alter table public.applications enable row level security;
alter table public.application_documents enable row level security;
alter table public.application_document_submissions enable row level security;
alter table public.application_document_allowances enable row level security;
alter table public.application_history enable row level security;
alter table public.notifications enable row level security;
alter table public.audit_log enable row level security;
alter table public.email_log enable row level security;
alter table public.application_appeals enable row level security;

revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

revoke update, delete on public.audit_log from public;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 5242880, array['application/pdf', 'image/jpeg', 'image/png'])
on conflict (id) do update
  set public = false,
      file_size_limit = 5242880,
      allowed_mime_types = array['application/pdf', 'image/jpeg', 'image/png'];
