-- Run this in the separate Supabase project used only for temporary previews.
create table if not exists public.store_previews (
  id uuid primary key,
  business_name text not null,
  business_type text not null,
  tagline text not null,
  logo_data text not null default '',
  created_at timestamptz not null,
  expires_at timestamptz not null
);

alter table public.store_previews enable row level security;
revoke all on public.store_previews from anon, authenticated;
grant all on public.store_previews to service_role;

create extension if not exists pg_cron with schema extensions;

select cron.unschedule(jobid)
from cron.job
where jobname = 'delete-expired-store-previews';

select cron.schedule(
  'delete-expired-store-previews',
  '*/15 * * * *',
  $$delete from public.store_previews where expires_at <= now()$$
);