# Parallax / Frontier Mercator — Project Handoff
*Prepared 2026-07-08 from the active Claude Code session. Safe to share — contains no passwords, API keys, or secrets.*

## What this project is
**Parallax** is a private geopolitical/investment intelligence platform built for **Frontier Mercator Group** (Chris Smith's company), focused on emerging/frontier markets (Africa + Latin America core mandate, 69 countries). Deployed at **frontiermercator.com** via Streamlit Community Cloud; code at GitHub `chrissmith333222/Frontier_Mercator` (branch `main`); local dev at `C:\Users\chris\OneDrive\Desktop\Frontier Mercator\Parallax`. Client-facing surfaces say "Frontier Mercator" only — the name "Parallax" is internal.

## Architecture at a glance
- **Data layer (12+ sources):** ACLED, GDELT (headline-enriched, geolocation-validated), World Bank (macro + demographics), IMF, AidData (Chinese dev finance), DFC, World Bank PPI, UNOSAT, Bellingcat, Infobae (Spanish), Jeune Afrique (French), NYT/WSJ; plus 22 commodity futures series (yfinance) and UNCTAD maritime/shipping statistics. All merged into `data/normalized/merged_dataset.json` (~94.6k events, ~71MB — GitHub hard limit is 100MB; raw source payloads were stripped to control size).
- **Analysis layer (Anthropic API, batch/offline — never live from the site except the chatbot):**
  - Per-country AI assessments for all 69 core-mandate countries (executive summary + security/political/economic/investment narratives + investment opportunities), regenerated on demand.
  - Correlation-discovery engine (statistical screen + LLM curation) → "Discovered Insights" tab.
  - **Investment thesis engine** (newest, the "so what/what now" layer): converts all platform intelligence into concrete theses, each mapped down the investment stack to **62 verified, actively-trading instruments** (regional ETFs → sector ETFs → commodities → single stocks) at 3 risk tiers (conservative/moderate/aggressive). First run produced 8 theses. Delisted/hallucinated tickers are structurally blocked from appearing.
  - Report-QA feedback loop: an LLM grades generated PDFs; its guidance auto-feeds future report generation.
- **Site (Streamlit):** tabs for Conflict & Security, Markets & Economy (sub-tabs: Macro Indicators, Investment Projects, Commodities, Shipping & Maritime, Demographics, Discovered Insights, Investment Insights), News & Social Signal, Great Power Competition, Long Form Pieces, Reports (PDF country/regional briefs with Chicago-style citations), unified intelligence map, live stock/commodity tickers (right-hand rail), Price History explorer (any tracked symbol, 1-day to lifetime), sidebar Research Assistant chatbot (the only live-API surface), 3D relationship network graphs.
- **Automation:** daily scheduled Claude Code task at ~9:09 AM local — refreshes news/GDELT/commodities/longform, rebuilds dataset, runs 290-test suite, commits+pushes if green, emails a status digest. Twice weekly (Mon/Thu): regenerates Discovered Insights + Investment Theses. Weekly (Mon): report QA + maritime stats. **The machine must be awake for the task to run.**
- **Auth (new):** Supabase email/password login gates the chatbot only (protects the metered Anthropic key); rest of site stays open. Admin member list visible only to Chris's email, enforced server-side by Postgres row-level security.

## Recent milestones (this session, July 6–8)
- All 69 country assessments regenerated on the final schema (3-paragraph executive summary; demographic-aware economic analysis) — zero failures.
- Investment Insights tab + verified instrument universe shipped.
- UNCTAD Shipping & Maritime tab shipped (liner connectivity through 2026Q2, container throughput, seaborne trade).
- Demographics tab + demographic indicators wired into reports and country assessments.
- Commodities tab (22 live series) + Price History explorer.
- Layout cleanup: sub-tabs directly under main tabs, market quotes moved to a right-hand rail, branded divider lines.
- Git-size crisis averted (merged dataset was heading past 88MB; now ~71MB and growing slowly).
- Brand guidelines PDF generated (`Frontier_Mercator_Brand_Guidelines.pdf` in repo root): colors w/ hex codes, fonts, logo usage, 3 new supplementary marks (Parallax product mark, Mercator tribute mark, world-map motif).
- Root-caused why site data was stale: the scheduled task ran but never committed (fixed — commit is now mandatory), and runs are skipped if the laptop is asleep.
- API billing clarified: the site/scripts use the metered Anthropic Console API (separate from Claude Pro/Max). Credits were exhausted once mid-batch; Chris topped up. Standing rule: Claude flags any token-heavy operation (full-catalog regenerations etc.) before running it.

## Open items — Chris's actions
1. **Supabase SQL (one paste away):** the member-list table still doesn't exist. Last error showed the *filename* was pasted into the SQL editor instead of the file's *contents*. Copy the SQL block from `supabase_setup.sql` (or from the chat message that contains it inline) into Supabase → SQL Editor → Run. Streamlit secrets are already added. Login/signup already work; this only unlocks the admin member list.
2. **Outlook email (research@frontiermercator.com) — in progress, root cause found:** the VPN was blocking Namecheap Private Email logins (their servers reject VPN IPs with generic auth failures), and days of Outlook retries likely triggered a temporary IP+mailbox lockout on the mail ports (webmail works; IMAP/SMTP still rejecting). Current plan: (a) close Outlook fully so it stops retrying, (b) re-type the webmail-verified password into `.env` `SMTP_PASSWORD` (no spaces — the current entry has a stray space and is 12 chars), (c) wait 30–60 min with zero login attempts, (d) Claude re-tests from the machine, (e) clear old entries in Windows Credential Manager, then re-add the account in **classic** Outlook (not "New Outlook") — manual IMAP: mail.privateemail.com, 993/SSL in, 465/SSL out, username = full email address. Keep the VPN off for mail or add an exception, or the cycle restarts. Fixing this also activates the daily digest emails.
3. **ReliefWeb API:** Chris is requesting an appname at apidoc.reliefweb.int (ingestion code is already written; add `RELIEFWEB_APPNAME` to `.env` when approved and the scheduled task will wire it in).
4. **UCDP conflict data:** requires emailing their maintainer for an access token (add as `UCDP_ACCESS_TOKEN` to `.env`).
5. **HTTPS + domain masking for frontiermercator.com:** currently a plain Namecheap redirect (http, shows streamlit.app URL). The fix is moving nameservers to Cloudflare (free) — gives real SSL on the domain plus masking. Needs Chris's go-ahead since it touches email DNS records; Claude will prep a full migration plan on request.

## Open items — build backlog
- PWA manifest/service worker for "install to home screen" mobile app experience (approved approach; native app deferred).
- FastAPI+React migration remains the eventual answer for truly instant UI, floating chat, click-a-ticker-to-chart, etc. (documented, not started).
- Telegram as next social source (needs Chris's my.telegram.org signup).
- Merged dataset trimming strategy (GDELT rolling window) if size passes ~75MB.

## Key facts for anyone picking this up
- Test suite: `python -m pytest tests/ -q` (290 tests, all passing as of this handoff).
- Data refresh: fetch/normalize scripts in `scripts/ingestion/`, then `python scripts/curation/build_merged_dataset.py`; data files are gitignored but force-tracked (`git add -f`).
- AI artifacts (assessments, insights, theses) are generated OFFLINE by scripts in `scripts/analysis/` and `scripts/analytics/`, committed as JSON, read statically by the deployed app. The Research Assistant chatbot is the only live API call on the site.
- Any new forced-tool LLM feature must route output through `_normalize_tool_output` (reasoning_agent.py) — malformed tool outputs (JSON-stringified arrays, double-nested payloads) have occurred live multiple times.
- Verify-before-build discipline: never trust a ticker symbol, RSS URL, or API endpoint without checking the real response first (this has caught delisted ETFs, wrong-identity tickers, and dead feeds repeatedly).
- Cost discipline: flag full-catalog LLM batch operations in chat before running; single-country regenerations and chatbot usage are cheap and routine.
