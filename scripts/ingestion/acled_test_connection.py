"""
meridian/scripts/ingestion/acled_test_connection.py

Run this FIRST, before building anything else, to confirm your ACLED credentials
are set up correctly. It performs a minimal API call (5 records, no filters) and
reports clearly whether auth + the read endpoint are both working.

Usage:
    python scripts/ingestion/acled_test_connection.py
"""

import sys
from pathlib import Path

# Allow running this script directly without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
from scripts.lib.acled_auth import get_auth_headers, ACLEDAuthError

ACLED_READ_URL = "https://acleddata.com/api/acled/read"


def main():
    print("MERIDIAN — ACLED Connection Test")
    print("=" * 50)

    print("\n[1/2] Requesting access token...")
    try:
        headers = get_auth_headers()
        print("      ✓ Authentication succeeded. Token acquired and cached.")
    except ACLEDAuthError as e:
        print(f"      ✗ Authentication FAILED: {e}")
        print("\nNext steps:")
        print("  1. Confirm .env exists in the project root with ACLED_EMAIL and ACLED_PASSWORD set")
        print("  2. Confirm those credentials work by logging into https://acleddata.com directly")
        print("  3. See docs/acled_setup.md for full setup instructions")
        sys.exit(1)

    print("\n[2/2] Fetching 5 sample records (no filters)...")
    try:
        response = requests.get(
            ACLED_READ_URL,
            headers=headers,
            params={"limit": 5, "_format": "json"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"      ✗ Network request FAILED: {e}")
        sys.exit(1)

    if response.status_code != 200:
        print(f"      ✗ API returned status {response.status_code}")
        print(f"        Response: {response.text[:500]}")
        print("\nThis usually means either:")
        print("  - Your account doesn't have access to this endpoint yet (check your myACLED access tier)")
        print("  - Your token expired mid-request (rare; just re-run this script)")
        sys.exit(1)

    payload = response.json()
    count = payload.get("count", "unknown")
    status = payload.get("status", "unknown")
    records = payload.get("data", [])

    print(f"      ✓ API call succeeded. status={status}, count={count}")

    if records:
        print(f"\nSample event returned:")
        sample = records[0]
        print(f"  Country:     {sample.get('country')}")
        print(f"  Event date:  {sample.get('event_date')}")
        print(f"  Event type:  {sample.get('event_type')}")
        print(f"  Fatalities:  {sample.get('fatalities')}")
        print(f"  Notes:       {str(sample.get('notes', ''))[:120]}...")
    else:
        print("\n⚠ Call succeeded but returned zero records. This is unusual for an")
        print("  unfiltered query — double check your account's access tier and data scope.")

    print("\n" + "=" * 50)
    print("Connection test PASSED. You're ready to build the full ingestion pipeline.")


if __name__ == "__main__":
    main()
