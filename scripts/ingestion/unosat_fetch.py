"""
scripts/ingestion/unosat_fetch.py

Fetches UNOSAT (UN Operational Satellite Applications Programme) products
-- satellite-based damage assessments, flood/disaster mapping, and
conflict-monitoring products -- via the Humanitarian Data Exchange (HDX)
CKAN API. This is part of the OSINT/imagery strategy: rather than
building our own computer-vision satellite pipeline, we ingest the
*conclusions* of an organization already doing rigorous imagery-based
analysis (same rationale as the Bellingcat source).

unosat.org itself is a client-side SPA with no accessible feed/API, but
UNOSAT publishes essentially all of its products as HDX datasets under its
own organization, with a fully open, documented, unauthenticated CKAN API
-- no bot-protection encountered (unlike World Bank's indicator API).

Usage (CLI):
    python scripts/ingestion/unosat_fetch.py --output raw_unosat.json

Usage (as a module):
    from scripts.ingestion.unosat_fetch import fetch_recent_products
    products = fetch_recent_products()
"""

import sys
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests

SEARCH_URL = "https://data.humdata.org/api/3/action/package_search"
PAGE_SIZE = 1000


def fetch_recent_products(max_products: int = 3000) -> list[dict]:
    """Paginates through HDX's package_search API filtered to the UNOSAT
    organization, newest first, until max_products is reached or the
    organization's full catalog is exhausted."""
    products = []
    start = 0
    while len(products) < max_products:
        response = requests.get(
            SEARCH_URL,
            params={
                "fq": "organization:unosat",
                "rows": PAGE_SIZE,
                "start": start,
                "sort": "metadata_modified desc",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=60,
        )
        if response.status_code != 200:
            raise RuntimeError(f"UNOSAT/HDX fetch failed: status {response.status_code}")

        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"UNOSAT/HDX API returned success=false: {payload}")

        page = payload["result"]["results"]
        if not page:
            break
        products.extend(page)
        start += PAGE_SIZE
        if len(page) < PAGE_SIZE:
            break

    return products[:max_products]


def main():
    parser = argparse.ArgumentParser(description="Fetch recent UNOSAT products from HDX")
    parser.add_argument("--max-products", type=int, default=3000,
                         help="Maximum number of products to fetch (default 3000; full catalog is ~1500).")
    parser.add_argument("--output", type=str, default=None,
                         help="Write raw JSON output to this file path. Omit to print to stdout.")
    args = parser.parse_args()

    products = fetch_recent_products(max_products=args.max_products)
    print(f"Fetched {len(products)} raw UNOSAT products", file=sys.stderr)

    output_json = json.dumps(products, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
