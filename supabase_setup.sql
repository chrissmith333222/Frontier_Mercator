-- supabase_setup.sql  (v4 -- visit counter; login gate retired 2026-07-08)
--
-- Chris removed the member login from the site (the chatbot is open again;
-- runaway-cost protection now comes from the monthly spend limit on his
-- Anthropic console account). What remains is an OPTIONAL anonymous visit
-- counter so he can see how much traffic frontiermercator.com gets with
-- data he owns (complementing Streamlit Cloud's built-in viewer stats).
--
-- To activate: copy everything below into the Supabase dashboard's SQL
-- Editor (SQL Editor -> New query -> paste the SQL TEXT, not a filename ->
-- Run) for project bfushelwyvkznaagqqdu. Until this runs, the site's
-- visit logging is a silent no-op -- nothing breaks either way.
--
-- Privacy: one row per visitor session, timestamp only. No IP, no name,
-- no email, nothing identifying.

create table if not exists public.site_visits (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now()
);

alter table public.site_visits enable row level security;

-- The site (anon key) may INSERT rows but never read, change, or delete
-- them -- a write-only counter. Even someone who extracts the public anon
-- key from the site can only add a row, same as visiting the page.
drop policy if exists "anyone can log a visit" on public.site_visits;
create policy "anyone can log a visit"
    on public.site_visits for insert
    to anon
    with check (true);

-- Read the counts in the Supabase dashboard (Table Editor -> site_visits),
-- or run e.g.:
--   select date_trunc('day', created_at) as day, count(*) as visits
--   from site_visits group by 1 order by 1 desc;
