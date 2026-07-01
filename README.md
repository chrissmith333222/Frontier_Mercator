# MERIDIAN — Geopolitical Intelligence Agent
## Project Scaffold: ACLED Integration (Module 1 of N)

This is the first data-layer module for the MERIDIAN deep research agent. It builds the
ACLED (Armed Conflict Location & Event Data) ingestion pipeline: OAuth authentication,
data normalization, and the n8n workflow that runs it on a schedule.

Each future data source (ReliefWeb, World Bank, GDELT, V-Dem, etc.) will be added as its
own module following the same pattern, so you can audit, test, and customize each one
independently before they're wired together into the full MERIDIAN pipeline.

---

## Folder structure

```
meridian/
├── README.md                          ← you are here
├── .env.example                       ← template for credentials (copy to .env, fill in, never commit)
├── schemas/
│   └── normalized_event.schema.json   ← the common JSON shape ALL data sources get mapped into
├── scripts/
│   ├── lib/
│   │   └── acled_auth.py              ← OAuth token fetch + refresh logic
│   └── ingestion/
│       ├── acled_fetch.py             ← pulls raw ACLED events
│       ├── acled_normalize.py         ← maps raw ACLED → normalized_event schema
│       └── acled_test_connection.py   ← run this FIRST to verify your credentials work
├── workflows/
│   └── meridian_acled_ingest.json     ← importable n8n workflow (schedule → fetch → normalize → store)
├── tests/
│   └── test_acled_normalize.py        ← unit tests for the normalization logic, no API calls needed
└── docs/
    └── acled_setup.md                 ← step-by-step credential setup, specific to ACLED's OAuth flow
```

---

## Setup order (do this exactly in sequence)

1. **Read `docs/acled_setup.md` first.** ACLED uses OAuth (username + password → access
   token + refresh token), not a simple static API key. The setup doc walks through
   getting your myACLED account approved and generating credentials correctly.

2. **Copy `.env.example` to `.env`** in this folder and fill in your own values. This file
   is already covered by a `.gitignore` entry (see below) so it never gets committed or
   shared. I will never ask you to paste its contents into chat.

3. **Run `scripts/ingestion/acled_test_connection.py`** locally (or in your n8n Execute
   Command node) to confirm authentication works before building anything else on top of it.

4. **Run the unit tests** in `tests/test_acled_normalize.py` — these don't need real
   credentials, they test the normalization logic against sample data, so you can verify
   the schema mapping is correct independent of the live API.

5. **Import `workflows/meridian_acled_ingest.json`** into n8n (Workflows → Import from
   File). It references credentials by name (`ACLED_EMAIL`, `ACLED_PASSWORD`) — you'll
   create those in n8n's own Credentials manager, not in this codebase.

6. Once this module runs cleanly on a schedule and you're happy with the output, we
   repeat this same pattern for ReliefWeb, World Bank, GDELT, and the rest.

---

## Design principles for this scaffold

**Normalize early.** Every data source has wildly different field names and structures.
ACLED uses `event_date`, `fatalities`, `inter1`/`inter2` actor codes. ReliefWeb uses
different fields entirely. The `normalized_event.schema.json` is the common contract —
every ingestion script's job is to map its source into that shape, so your downstream
risk-scoring and RAG-retrieval agents only ever have to understand ONE format, not five.

**Separate auth from fetch from normalize.** Three different scripts, three different
jobs. This means when ACLED changes their auth flow (which they just did, migrating off
the old API key system in September 2025), you only touch `acled_auth.py` — the fetch
and normalize logic don't change.

**Test without credentials.** The unit tests run against sample/fixture data, not the
live API. This lets you (or me, later) verify logic changes quickly without burning API
calls or needing live credentials in a test environment.

**n8n workflow is a thin wrapper.** The actual logic lives in Python scripts, not buried
inside n8n's visual nodes. This means the workflow is easy to read, the logic is
version-controllable and testable outside of n8n, and you can run the same scripts from
the command line for debugging.
