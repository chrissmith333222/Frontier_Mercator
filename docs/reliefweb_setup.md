# ReliefWeb (UN OCHA) — Setup

ReliefWeb's API is free, but since **1 November 2025** it requires a
pre-approved `appname` for every call — a made-up string will be rejected
(and daily quota is 1,000 calls per appname, so it's tied to your identity).

## Steps

1. Go to the ReliefWeb API documentation site: https://apidoc.reliefweb.int/
2. Find the appname request form (linked from the docs homepage). Fill in:
   - Your organization name (e.g. "Frontier Mercator Group")
   - The purpose of your application (e.g. "Geopolitical/investment intelligence
     platform for Africa and Latin America emerging markets — humanitarian and
     displacement signal ingestion")
   - The form will generate or ask you to propose an appname combining your org
     name + purpose + some random characters (e.g. `frontier-mercator-x7k2`)
3. Submit the form. ReliefWeb staff review requests and notify you by email —
   this isn't instant, budget a few business days.
4. Once approved, copy `.env.example` to `.env` if you haven't already, and set:
   ```
   RELIEFWEB_APPNAME=your-approved-appname
   ```
5. Test the connection:
   ```
   python scripts/ingestion/reliefweb_fetch.py --days-back 3 --country Mali
   ```
   If it returns reports instead of an error, you're set.

## Notes

- No password/OAuth like ACLED — just the appname on every request.
- The normalization logic (`reliefweb_normalize.py`) is already tested against
  fixture data and doesn't need live credentials to verify — see
  `tests/test_reliefweb_normalize.py`.
- ReliefWeb reports often reference multiple countries; normalization expands
  those into one event per country, consistent with every other MERIDIAN source.
