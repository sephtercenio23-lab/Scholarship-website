alter table public.term_scholarships
  add column if not exists deadline_at timestamptz;
