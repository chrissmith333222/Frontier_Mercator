-- supabase_setup.sql
--
-- One-time setup for Frontier Mercator's member auth. Paste this whole file
-- into the Supabase dashboard's SQL Editor (left sidebar -> SQL Editor ->
-- New query -> paste -> Run) for project bfushelwyvkznaagqqdu.
--
-- What it does:
--   1. Creates a public.profiles table mirroring each signup (name, email,
--      signup date) -- auth.users itself is not readable with the anon key,
--      which is why this mirror exists.
--   2. Auto-fills it via a trigger whenever someone signs up.
--   3. Locks it down with row-level security so ONLY the admin email can
--      read the member list. This is enforced by Postgres itself -- even
--      someone who extracts the anon key from the site cannot read it.

create table if not exists public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    full_name text,
    email text,
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Trigger: copy every new auth user into profiles automatically.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
    insert into public.profiles (id, full_name, email)
    values (
        new.id,
        coalesce(new.raw_user_meta_data ->> 'full_name', ''),
        new.email
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- RLS: only the admin email may read the member list. No insert/update/
-- delete policies exist at all -- the trigger above runs as definer, and
-- nobody else has any reason to write to this table.
drop policy if exists "admin can read all profiles" on public.profiles;
create policy "admin can read all profiles"
    on public.profiles for select
    using (auth.jwt() ->> 'email' = 'chrissmith333222@gmail.com');
