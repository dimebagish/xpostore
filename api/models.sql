-- Run this script in the Supabase SQL Editor. It is safe to rerun.
-- Flask performs database access server-side with the service-role key;
-- never expose that key in browser code or public client configuration.

begin;

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password text not null,
  phone text,
  address text,
  role text not null default 'customer' check (role in ('customer', 'admin')),
  created_at timestamptz not null default now()
);

-- Bring the original auth.users-linked profile schema in line with the app's
-- current custom signup flow, which creates profiles without Supabase Auth.
alter table public.profiles drop constraint if exists profiles_id_fkey;
alter table public.profiles alter column id set default gen_random_uuid();
alter table public.profiles add column if not exists email text;
alter table public.profiles add column if not exists password text;
alter table public.profiles add column if not exists phone text;
alter table public.profiles add column if not exists address text;
alter table public.profiles add column if not exists role text default 'customer';
alter table public.profiles add column if not exists created_at timestamptz default now();

create table if not exists public.admins (
  id bigserial primary key,
  username text not null unique,
  email text not null unique,
  password text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.categories (
  id bigserial primary key,
  cat_name text not null unique,
  created_at timestamptz not null default now()
);

do $$
begin
  if to_regclass('public.items') is null and to_regclass('public.phones') is not null then
    alter table public.phones rename to items;
  end if;
  if to_regclass('public.item_media') is null and to_regclass('public.phone_media') is not null then
    alter table public.phone_media rename to item_media;
  end if;
  if to_regclass('public.item_age_prices') is null and to_regclass('public.phone_age_prices') is not null then
    alter table public.phone_age_prices rename to item_age_prices;
  end if;

  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'items' and column_name = 'source_phone_id')
     and not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'items' and column_name = 'source_item_id') then
    alter table public.items rename column source_phone_id to source_item_id;
  end if;
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'item_media' and column_name = 'phone_id')
     and not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'item_media' and column_name = 'item_id') then
    alter table public.item_media rename column phone_id to item_id;
  end if;
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'item_age_prices' and column_name = 'phone_id')
     and not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'item_age_prices' and column_name = 'item_id') then
    alter table public.item_age_prices rename column phone_id to item_id;
  end if;
  if to_regclass('public.orders') is not null then
    if to_regclass('public.orders_item_id_idx') is null and to_regclass('public.orders_product_id_idx') is not null then
      alter index public.orders_product_id_idx rename to orders_item_id_idx;
    end if;
    if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'orders' and column_name = 'product_id')
       and not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'orders' and column_name = 'item_id') then
      alter table public.orders rename column product_id to item_id;
    end if;
    if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'orders' and column_name = 'legacy_phone_id')
       and not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'orders' and column_name = 'legacy_item_id') then
      alter table public.orders rename column legacy_phone_id to legacy_item_id;
    end if;
  end if;

  if to_regclass('public.items_id_seq') is null and to_regclass('public.phones_id_seq') is not null then
    alter sequence public.phones_id_seq rename to items_id_seq;
  end if;
  if to_regclass('public.item_media_id_seq') is null and to_regclass('public.phone_media_id_seq') is not null then
    alter sequence public.phone_media_id_seq rename to item_media_id_seq;
  end if;
  if to_regclass('public.item_age_prices_id_seq') is null and to_regclass('public.phone_age_prices_id_seq') is not null then
    alter sequence public.phone_age_prices_id_seq rename to item_age_prices_id_seq;
  end if;

  if to_regclass('public.items_status_idx') is null and to_regclass('public.phones_status_idx') is not null then
    alter index public.phones_status_idx rename to items_status_idx;
  end if;
  if to_regclass('public.items_category_idx') is null and to_regclass('public.phones_category_idx') is not null then
    alter index public.phones_category_idx rename to items_category_idx;
  end if;
  if to_regclass('public.items_admin_id_idx') is null and to_regclass('public.phones_admin_id_idx') is not null then
    alter index public.phones_admin_id_idx rename to items_admin_id_idx;
  end if;
  if to_regclass('public.items_buyer_email_idx') is null and to_regclass('public.phones_buyer_email_idx') is not null then
    alter index public.phones_buyer_email_idx rename to items_buyer_email_idx;
  end if;
  if to_regclass('public.items_source_item_id_idx') is null and to_regclass('public.phones_source_phone_id_idx') is not null then
    alter index public.phones_source_phone_id_idx rename to items_source_item_id_idx;
  end if;
  if to_regclass('public.item_media_item_id_idx') is null and to_regclass('public.phone_media_phone_id_idx') is not null then
    alter index public.phone_media_phone_id_idx rename to item_media_item_id_idx;
  end if;
  if to_regclass('public.item_age_prices_item_id_idx') is null and to_regclass('public.phone_age_prices_phone_id_idx') is not null then
    alter index public.phone_age_prices_phone_id_idx rename to item_age_prices_item_id_idx;
  end if;

  if to_regclass('public.items') is not null then
    if exists (select 1 from pg_constraint where conrelid = 'public.items'::regclass and conname = 'phones_pkey') then
      alter table public.items rename constraint phones_pkey to items_pkey;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.items'::regclass and conname = 'phones_status_check') then
      alter table public.items rename constraint phones_status_check to items_status_check;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.items'::regclass and conname = 'phones_admin_id_fkey') then
      alter table public.items rename constraint phones_admin_id_fkey to items_admin_id_fkey;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.items'::regclass and conname = 'phones_source_phone_id_fkey') then
      alter table public.items rename constraint phones_source_phone_id_fkey to items_source_item_id_fkey;
    end if;
  end if;
  if to_regclass('public.item_media') is not null then
    if exists (select 1 from pg_constraint where conrelid = 'public.item_media'::regclass and conname = 'phone_media_pkey') then
      alter table public.item_media rename constraint phone_media_pkey to item_media_pkey;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.item_media'::regclass and conname = 'phone_media_phone_id_fkey') then
      alter table public.item_media rename constraint phone_media_phone_id_fkey to item_media_item_id_fkey;
    end if;
  end if;
  if to_regclass('public.item_age_prices') is not null then
    if exists (select 1 from pg_constraint where conrelid = 'public.item_age_prices'::regclass and conname = 'phone_age_prices_pkey') then
      alter table public.item_age_prices rename constraint phone_age_prices_pkey to item_age_prices_pkey;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.item_age_prices'::regclass and conname = 'phone_age_prices_phone_id_fkey') then
      alter table public.item_age_prices rename constraint phone_age_prices_phone_id_fkey to item_age_prices_item_id_fkey;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.item_age_prices'::regclass and conname = 'phone_age_prices_phone_id_age_key') then
      alter table public.item_age_prices rename constraint phone_age_prices_phone_id_age_key to item_age_prices_item_id_age_key;
    end if;
  end if;
  if to_regclass('public.orders') is not null then
    if exists (select 1 from pg_constraint where conrelid = 'public.orders'::regclass and conname = 'orders_product_id_fkey') then
      alter table public.orders rename constraint orders_product_id_fkey to orders_item_id_fkey;
    end if;
    if exists (select 1 from pg_constraint where conrelid = 'public.orders'::regclass and conname = 'orders_legacy_phone_id_key') then
      alter table public.orders rename constraint orders_legacy_phone_id_key to orders_legacy_item_id_key;
    end if;
  end if;
end;
$$;

create table if not exists public.items (
  id bigserial primary key,
  model text not null,
  specs text,
  condition text,
  price numeric(12, 2) not null check (price >= 0),
  status text not null default 'Available' check (status = 'Available'),
  category text,
  admin_id bigint references public.admins(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Add fields used by the Flask app when upgrading the original items table.
alter table public.items add column if not exists category text;
alter table public.items add column if not exists admin_id bigint;
alter table public.items add column if not exists buyer_name text;
alter table public.items add column if not exists buyer_address text;
alter table public.items add column if not exists payment_method text;
alter table public.items add column if not exists payment_receipt_url text;
alter table public.items add column if not exists purchase_time timestamptz;
alter table public.items add column if not exists tracking_number text;
alter table public.items add column if not exists booking_time timestamptz;
alter table public.items add column if not exists selling_time timestamptz;
alter table public.items add column if not exists buyer_email text;
alter table public.items add column if not exists buyer_phone text;
alter table public.items add column if not exists payment_status text;
alter table public.items add column if not exists full_payment boolean default false;
alter table public.items add column if not exists shipping_status text default 'Pending';
alter table public.items add column if not exists source_item_id bigint references public.items(id);
alter table public.items add column if not exists created_at timestamptz default now();
alter table public.items add column if not exists updated_at timestamptz default now();

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname in ('phones_admin_id_fkey', 'items_admin_id_fkey')
      and conrelid = 'public.items'::regclass
  ) then
    alter table public.items
      add constraint items_admin_id_fkey
      foreign key (admin_id) references public.admins(id) on delete set null;
  end if;
end;
$$;

create table if not exists public.item_media (
  id bigserial primary key,
  item_id bigint not null references public.items(id) on delete cascade,
  url text not null,
  kind text not null default 'image' check (kind in ('image', 'video')),
  created_at timestamptz not null default now()
);

create table if not exists public.item_age_prices (
  id bigserial primary key,
  item_id bigint not null references public.items(id) on delete cascade,
  age text not null,
  price numeric(12, 2) not null check (price >= 0),
  created_at timestamptz not null default now(),
  unique (item_id, age)
);

alter table public.items add column if not exists purchased_age text;

create table if not exists public.orders (
  id bigserial primary key,
  item_id bigint not null references public.items(id) on delete restrict,
  model text not null,
  specs text,
  condition text,
  category text,
  purchased_age text,
  price numeric(12, 2) not null check (price >= 0),
  admin_id bigint references public.admins(id) on delete set null,
  buyer_name text,
  buyer_email text,
  buyer_phone text,
  buyer_address text,
  payment_method text,
  payment_receipt_url text,
  payment_status text,
  full_payment boolean not null default false,
  status text not null default 'Booked'
    check (status in ('Booked', 'Sold', 'Cancelled')),
  shipping_status text default 'Pending',
  booking_time timestamptz,
  purchase_time timestamptz,
  selling_time timestamptz,
  tracking_number text,
  legacy_item_id bigint unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.orders add column if not exists category text;

-- Preserve orders from the previous schema before returning catalog rows to inventory.
insert into public.orders (
  legacy_item_id, item_id, model, specs, condition, category, purchased_age, price,
  admin_id, buyer_name, buyer_email, buyer_phone, buyer_address,
  payment_method, payment_receipt_url, payment_status, full_payment, status,
  shipping_status, booking_time, purchase_time, selling_time, tracking_number
)
select
  p.id,
  coalesce(p.source_item_id, p.id),
  p.model,
  p.specs,
  p.condition,
  p.category,
  p.purchased_age,
  p.price,
  p.admin_id,
  p.buyer_name,
  p.buyer_email,
  p.buyer_phone,
  p.buyer_address,
  p.payment_method,
  p.payment_receipt_url,
  p.payment_status,
  coalesce(p.full_payment, false),
  case when p.status in ('Booked', 'Sold') then p.status else 'Cancelled' end,
  p.shipping_status,
  p.booking_time,
  p.purchase_time,
  p.selling_time,
  p.tracking_number
from public.items p
where p.source_item_id is not null or p.status in ('Booked', 'Sold')
on conflict (legacy_item_id) do nothing;

update public.items p
set status = 'Available',
    price = coalesce((
      select min(ap.price)
      from public.item_age_prices ap
      where ap.item_id = p.id
    ), p.price),
    buyer_name = null,
    buyer_email = null,
    buyer_phone = null,
    buyer_address = null,
    payment_method = null,
    payment_receipt_url = null,
    payment_status = null,
    full_payment = false,
    shipping_status = 'Pending',
    booking_time = null,
    purchase_time = null,
    selling_time = null,
    tracking_number = null,
    purchased_age = null
where p.source_item_id is null
  and p.status in ('Booked', 'Sold')
  and exists (
    select 1 from public.orders o
    where o.legacy_item_id = p.id and o.item_id = p.id
  );

delete from public.items where source_item_id is not null;

alter table public.items drop constraint if exists phones_status_check;
alter table public.items drop constraint if exists items_status_check;
alter table public.items add constraint items_status_check check (status = 'Available');
alter table public.items
  drop column if exists source_item_id,
  drop column if exists buyer_name,
  drop column if exists buyer_email,
  drop column if exists buyer_phone,
  drop column if exists buyer_address,
  drop column if exists payment_method,
  drop column if exists payment_receipt_url,
  drop column if exists payment_status,
  drop column if exists full_payment,
  drop column if exists shipping_status,
  drop column if exists booking_time,
  drop column if exists purchase_time,
  drop column if exists selling_time,
  drop column if exists tracking_number,
  drop column if exists purchased_age;

create index if not exists items_status_idx on public.items(status);
create index if not exists items_category_idx on public.items(category);
create index if not exists items_admin_id_idx on public.items(admin_id);
create index if not exists orders_item_id_idx on public.orders(item_id);
create index if not exists orders_admin_id_idx on public.orders(admin_id);
create index if not exists orders_buyer_email_idx on public.orders(buyer_email);
create index if not exists orders_status_purchase_time_idx on public.orders(status, purchase_time desc);
create index if not exists item_media_item_id_idx on public.item_media(item_id);
create index if not exists item_age_prices_item_id_idx on public.item_age_prices(item_id);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists phones_set_updated_at on public.items;
drop trigger if exists items_set_updated_at on public.items;
create trigger items_set_updated_at
  before update on public.items
  for each row execute function public.set_updated_at();

drop trigger if exists orders_set_updated_at on public.orders;
create trigger orders_set_updated_at
  before update on public.orders
  for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.admins enable row level security;
alter table public.categories enable row level security;
alter table public.items enable row level security;
alter table public.orders enable row level security;
alter table public.item_media enable row level security;
alter table public.item_age_prices enable row level security;

-- All app data access is performed by the trusted Flask server using its
-- service-role key. The anon/authenticated roles get no table access.
drop policy if exists "Public can insert own profile" on public.profiles;
drop policy if exists "Users can select/update own profile" on public.profiles;
drop policy if exists "Public can read categories" on public.categories;
drop policy if exists "Anyone can read phones" on public.items;
drop policy if exists "Public can read phones" on public.items;
drop policy if exists "Anyone can read items" on public.items;
drop policy if exists "Public can read items" on public.items;
drop policy if exists "Anyone can read media" on public.item_media;
drop policy if exists "Public can read item media" on public.item_media;

revoke all on public.profiles, public.admins, public.categories,
  public.items, public.orders, public.item_media, public.item_age_prices from anon, authenticated;
grant all on public.profiles, public.admins, public.categories, public.items, public.item_media
  to service_role;
grant all on public.orders to service_role;
grant all on public.item_age_prices to service_role;
grant usage, select on sequence public.admins_id_seq, public.categories_id_seq,
  public.items_id_seq, public.item_media_id_seq, public.item_age_prices_id_seq to service_role;
grant usage, select on sequence public.orders_id_seq to service_role;

commit;