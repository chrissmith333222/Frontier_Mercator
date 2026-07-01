"""
Parallax API — Frontier Mercator Group
REST API backend for ACLED and other geopolitical data sources.
Wraps Python ingestion pipelines and exposes them as HTTP endpoints.
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import json
import sys

# Add scripts to path so we can import them
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.ingestion.acled_fetch import fetch_recent_events
from scripts.ingestion.acled_normalize import normalize_batch

app = FastAPI(
    title="Parallax API",
    description="Intelligence for the Frontier — Real-time geopolitical analysis API",
    version="1.0.0"
)

# Allow requests from Retool and localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Utility Functions ---

def load_cached_events(max_age_hours: int = 24) -> list | None:
    """Load previously normalized events from cache if available."""
    cache_path = Path(__file__).parent / "data" / "normalized" / "acled_latest_normalized.json"
    if cache_path.exists():
        with open(cache_path, 'r') as f:
            return json.load(f)
    return None


# --- Endpoints ---

@app.get("/")
def root():
    """Health check and API info."""
    return {
        "name": "Parallax API",
        "version": "1.0.0",
        "description": "Intelligence for the Frontier",
        "endpoints": {
            "events": "/api/events",
            "events_by_country": "/api/events/{country}",
            "high_severity": "/api/events/severity/critical",
            "health": "/health"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "parallax-api"}


@app.get("/api/events")
def get_events(
    days_back: int = Query(7, ge=1, le=3650, description="Days to fetch (1-3650)"),
    min_severity: float = Query(0, ge=0, le=10, description="Minimum severity score (0-10)"),
    region: str = Query(None, description="Filter by region (e.g., 'West Africa / Sahel')"),
    country: str = Query(None, description="Filter by country"),
    refresh: bool = Query(False, description="Force refresh from ACLED (bypass cache)")
):
    """
    Get normalized ACLED events with optional filtering.

    **Query parameters:**
    - `days_back`: How many days back to fetch (default 7)
    - `min_severity`: Minimum severity score 0-10 (default 0)
    - `region`: Filter by MERIDIAN region
    - `country`: Filter by country name
    - `refresh`: Force fresh fetch from ACLED API (slower, but latest data)

    **Example:**
    `/api/events?days_back=7&min_severity=6&region=West%20Africa%20/%20Sahel`
    """
    try:
        # Try to use cached data first
        if not refresh:
            cached = load_cached_events()
            if cached:
                events = cached
            else:
                # Fetch and normalize
                raw_events = fetch_recent_events(days_back=days_back)
                events = normalize_batch(raw_events)
        else:
            # Force refresh from API
            raw_events = fetch_recent_events(days_back=days_back)
            events = normalize_batch(raw_events)

        # Apply filters
        filtered = events

        if min_severity > 0:
            filtered = [e for e in filtered if e.get('severity_score', 0) >= min_severity]

        if region:
            filtered = [e for e in filtered if e.get('region') == region]

        if country:
            filtered = [e for e in filtered if e.get('country', '').lower() == country.lower()]

        return {
            "count": len(filtered),
            "filters": {
                "days_back": days_back,
                "min_severity": min_severity,
                "region": region,
                "country": country
            },
            "events": filtered
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching events: {str(e)}")


@app.get("/api/events/{country}")
def get_events_by_country(
    country: str,
    min_severity: float = Query(0, ge=0, le=10),
    days_back: int = Query(30, ge=1, le=3650)
):
    """Get events for a specific country."""
    try:
        raw_events = fetch_recent_events(days_back=days_back)
        events = normalize_batch(raw_events)

        filtered = [
            e for e in events
            if e.get('country', '').lower() == country.lower()
            and e.get('severity_score', 0) >= min_severity
        ]

        return {
            "country": country,
            "count": len(filtered),
            "events": filtered
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching events: {str(e)}")


@app.get("/api/events/severity/critical")
def get_critical_events(days_back: int = Query(30, ge=1, le=3650)):
    """Get high-severity events (severity >= 7)."""
    try:
        raw_events = fetch_recent_events(days_back=days_back)
        events = normalize_batch(raw_events)

        critical = [e for e in events if e.get('severity_score', 0) >= 7]

        return {
            "severity_threshold": 7,
            "count": len(critical),
            "events": sorted(critical, key=lambda x: x.get('severity_score', 0), reverse=True)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching events: {str(e)}")


@app.get("/api/summary")
def get_summary(days_back: int = Query(30, ge=1, le=3650)):
    """Get summary statistics of events."""
    try:
        raw_events = fetch_recent_events(days_back=days_back)
        events = normalize_batch(raw_events)

        if not events:
            return {"error": "No events found", "count": 0}

        critical = len([e for e in events if e.get('severity_score', 0) >= 7])
        high = len([e for e in events if 5 <= e.get('severity_score', 0) < 7])
        countries = len(set(e.get('country') for e in events))
        total_fatalities = sum(int(e.get('fatalities', 0) or 0) for e in events)

        return {
            "period_days": days_back,
            "total_events": len(events),
            "critical_events": critical,
            "high_severity_events": high,
            "unique_countries": countries,
            "total_fatalities": total_fatalities
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
