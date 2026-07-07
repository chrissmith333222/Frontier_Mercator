-- supabase_setup.sql  (v3 -- zero references to the auth schema)
--
-- One-time setup for Frontier Mercator's member auth. Paste this whole file
-- into the Supabase dashboard's SQL Editor (left sidebar -> SQL Editor ->
-- New query -> paste -> Run) for project bfushelwyvkznaagqqdu.
--
-- v3 note: v1 failed on a trigger on auth.users; v2 removed the trigger
-- but still had a foreign key REFERENCING auth.users, which can also hit
-- the locked-down auth schema on newer projects. This version touches
-- ONLY the public schema -- nothing here can fail on auth-schema
-- permissions. The id column still holds the Supabase auth user's uuid
-- (the dashboard supplies it on login); it's just no longer a declared
-- foreign key, which costs us nothing except automatic cascade-delete.

create table if not exists public.profiles (
    id uuid primary key,
    full_name text,
    email text,
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Members may create/update ONLY their own row (the dashboard does this
-- automatically on each login). auth.uid() reads the caller's verified
-- JWT -- a member cannot forge someone else's id.
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
