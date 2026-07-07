-- supabase_setup.sql  (v2 -- no auth.users trigger)
--
-- One-time setup for Frontier Mercator's member auth. Paste this whole file
-- into the Supabase dashboard's SQL Editor (left sidebar -> SQL Editor ->
-- New query -> paste -> Run) for project bfushelwyvkznaagqqdu.
--
-- v2 note: the original version created a trigger on auth.users, which
-- fails with a permissions error on newer Supabase projects (the auth
-- schema is locked down, even for the SQL editor). This version needs no
-- trigger: the dashboard upserts the member's own profile row right after
-- each successful login instead, and row-level security guarantees a user
-- can only ever write their OWN row and only the admin can read the list.

create table if not exists public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    full_name text,
    email text,
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Members may create/update ONLY their own row (the dashboard does this
-- automatically on login).
drop policy if exists "users insert own profile" on public.profiles;
create policy "users insert own profile"
    on public.profiles for insert
    with check (auth.uid() = id);

drop policy if exists "users update own profile" on public.profiles;
create policy "users update own profile"
    on public.profiles for update
    using (auth.uid() = id)
    with check (auth.uid() = id);

-- ONLY the admin email may read the member list. Enforced by Postgres
-- itself -- even someone who extracts the public anon key from the site
-- cannot read it.
drop policy if exists "admin can read all profiles" on public.profiles;
create policy "admin can read all profiles"
    on public.profiles for select
    using (auth.jwt() ->> 'email' = 'chrissmith333222@gmail.com');
