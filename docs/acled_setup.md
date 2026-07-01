# ACLED Setup Guide for MERIDIAN

ACLED changed their authentication system in late 2025, moving from a simple static
API key to a full OAuth flow (the kind where a username/password exchange gets you a
temporary access token, similar to how many banking or enterprise APIs work). This
guide is written for the *current* system, not the older API-key version you may see
referenced in older tutorials or Stack Overflow answers.

---

## Step 1 — Register for a myACLED account

Go to **https://acleddata.com/user/re-activate** (this is the correct registration/
reactivation URL even for brand-new accounts under the new system).

A few things that affect your access level:
- **Use an institutional or organizational email address if you have one** (a
  university, company, or think tank domain). Generic addresses (gmail, yahoo, etc.)
  are automatically placed in the lower "Open myACLED" public access tier, which has
  more restrictions on data freshness and volume.
- If you're registering as an individual without an institutional affiliation, that's
  fine — you'll just start on the public tier, which is still genuinely useful for a
  personal research tool. You can request elevated access later by emailing ACLED's
  access team if your use case grows.
- You'll be asked to accept ACLED's Terms of Use, which includes their attribution
  requirement — any output from your MERIDIAN tool that uses ACLED data should credit
  ACLED per their attribution policy (this is a real legal requirement of using their
  data, not optional).

## Step 2 — Confirm your account is active

After registering, check your email for a confirmation/activation link. Until you
click this, authentication calls will fail even with the correct password.

## Step 3 — Add your credentials to MERIDIAN's `.env` file

In your `meridian/` project folder:

1. Copy `.env.example` to a new file named `.env`
2. Open `.env` in a text editor (not in any chat with Claude — this file should never
   be pasted into a conversation)
3. Fill in:
   ```
   ACLED_EMAIL=the-email-you-registered-with@yourdomain.com
   ACLED_PASSWORD=your-actual-acled-password
   ACLED_CLIENT_ID=acled
   ```
4. Save the file. It's already excluded from version control via `.gitignore`.

**Important — how this is different from the old system:** you are NOT generating a
static "API key" anywhere in the ACLED dashboard. Your email and password themselves
are what `acled_auth.py` uses to request a temporary access token (valid about 24
hours) plus a refresh token. The script handles requesting, caching, and refreshing
these tokens automatically — you should never need to manually generate or copy a
token yourself.

## Step 4 — Run the connection test

From the `meridian/` folder:

```bash
pip install requests python-dotenv --break-system-packages
python3 scripts/ingestion/acled_test_connection.py
```

You should see:
```
[1/2] Requesting access token...
      ✓ Authentication succeeded. Token acquired and cached.
[2/2] Fetching 5 sample records (no filters)...
      ✓ API call succeeded. status=..., count=...
```

### If authentication fails

- **"ACLED_EMAIL and ACLED_PASSWORD must be set"** — your `.env` file either doesn't
  exist yet (did you copy it from `.env.example`?) or wasn't filled in.
- **"Token request failed with status 401" or 403** — double check your password is
  correct by logging into acleddata.com directly in a browser. Also confirm you
  clicked the email activation link.
- **"Token request failed with status 429"** — you're being rate-limited; wait a few
  minutes and retry. ACLED's terms ask users to be measured in request frequency.
- **Call succeeds but returns 0 records** — this can happen on a brand-new public-tier
  account if your access scope hasn't been provisioned yet; this sometimes takes up
  to a day after registration. If it persists, email ACLED's access team.

## Step 5 — Set up n8n credentials (separate from the .env file)

When you import `workflows/meridian_acled_ingest.json`, the workflow calls your local
Python scripts via Execute Command nodes — which means n8n itself doesn't need its
own separate credential entry for ACLED, since the Python scripts read from `.env`
directly. This is the simplest setup for a personal/local n8n instance.

If you later move to n8n Cloud or a remote server (rather than running n8n locally
alongside this project folder), you'd instead want to set `ACLED_EMAIL` and
`ACLED_PASSWORD` as environment variables on that server, or migrate to n8n's native
credential manager and rewrite the auth call as an HTTP Request node instead of a
Python script call. We can build that version later if/when you outgrow local-only
operation.

## A note on usage etiquette

ACLED is a research nonprofit providing this data largely for free. Their docs
explicitly ask users to be "respectful and measured" in usage and to cache results
rather than re-fetching unnecessarily. The MERIDIAN scaffold's 6-hour default polling
interval (in the n8n workflow) and the token caching in `acled_auth.py` are both
designed with this in mind — there's no reason to poll more aggressively than that for
a personal monitoring tool, and doing so risks your account being flagged for misuse.
