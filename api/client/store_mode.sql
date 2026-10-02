-- Run this in the primary store Supabase project.
create table if not exists public.store_runtime_config (
  id boolean primary key default true check (id is true),
  mode text not null default 'client' check (mode in ('demo', 'client')),
  updated_at timestamptz not null default now()
);

create or replace function public.validate_store_runtime_mode()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.mode is null or new.mode not in ('demo', 'client') then
    raise exception 'Store mode must be demo or client.';
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists validate_store_runtime_mode on public.store_runtime_config;
create trigger validate_store_runtime_mode
before insert or update on public.store_runtime_config
for each row execute function public.validate_store_runtime_mode();

alter table public.store_runtime_config enable row level security;
revoke all on public.store_runtime_config from anon, authenticated;
grant select on public.store_runtime_config to service_role;

insert into public.store_runtime_config (id, mode)
values (true, 'client')
on conflict (id) do nothing;

-- Switch modes in the Supabase SQL editor:
-- update public.store_runtime_config set mode = 'demo' where id is true;
-- update public.store_runtime_config set mode = 'client' where id is true;