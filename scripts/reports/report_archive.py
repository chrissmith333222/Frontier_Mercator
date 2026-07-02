"""
scripts/reports/report_archive.py

Persists generated PDF reports (country briefs, regional summaries,
custom cross-cutting analyses) to a browsable archive, so past reports
can be filtered/re-downloaded instead of only existing as an ephemeral
download the moment they're generated.

Deliberately file-based and git-committed (data/reports_history/, same
pattern as data/analysis/) rather than relying on writes made from the
live deployed Streamlit app to persist: Streamlit Community Cloud's
filesystem is ephemeral and resets on redeploy/sleep-wake, so anything
written only at runtime on the deployed site would silently vanish. The
dashboard's "Generate ... Brief" buttons still archive on click for local
dev convenience, but the durable path is running this locally and
committing the result -- same as every other cached-artifact pattern in
this project (merged_dataset.json, country assessments, custom analyses).

Usage (as a module):
    from scripts.reports.report_archive import archive_report, list_archived_reports
    path = archive_report(pdf_bytes, report_type="country", label="Kenya")
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARCHIVE_DIR = REPO_ROOT / "data" / "reports_history"


def archive_report(pdf_bytes: bytes, report_type: str, label: str, output_dir: Path = ARCHIVE_DIR) -> Path:
    """Saves a generated PDF plus a metadata sidecar JSON to the archive.
    `report_type` is one of "country", "regional", "custom". `label` is
    the country/region name or (for custom) the query text. Returns the
    path to the metadata JSON (the PDF sits alongside it with the same
    stem)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    slug_source = f"{report_type}:{label}:{generated_at}"
    file_id = hashlib.sha256(slug_source.encode("utf-8")).hexdigest()[:12]

    pdf_path = output_dir / f"{file_id}.pdf"
    meta_path = output_dir / f"{file_id}.json"

    pdf_path.write_bytes(pdf_bytes)
    meta_path.write_text(json.dumps({
        "id": file_id,
        "report_type": report_type,
        "label": label,
        "generated_at": generated_at,
        "pdf_filename": pdf_path.name,
    }, indent=2), encoding="utf-8")

    return meta_path


def list_archived_reports(archive_dir: Path = ARCHIVE_DIR) -> list[dict]:
    """Returns every archived report's metadata (newest first), each
    annotated with the full path to its PDF for direct reading. Returns
    an empty list if nothing has been archived yet."""
    if not archive_dir.exists():
        return []
    reports = []
    for meta_path in archive_dir.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        pdf_path = archive_dir / meta["pdf_filename"]
        if pdf_path.exists():
            meta["pdf_path"] = str(pdf_path)
            reports.append(meta)
    return sorted(reports, key=lambda r: r.get("generated_at", ""), reverse=True)
