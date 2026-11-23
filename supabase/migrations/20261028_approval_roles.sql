alter table public.users drop constraint if exists users_role_check;
alter table public.users
  add constraint users_role_check
  check (role in ('student', 'staff', 'admin', 'president', 'executive_president', 'super_admin'));
