"""
tests/test_report_archive.py

Tests report_archive's save/list logic with a temporary directory --
no real PDF generation or dashboard needed.

Usage:
    python -m pytest tests/test_report_archive.py -v
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.reports.report_archive import archive_report, list_archived_reports


def test_archive_report_writes_pdf_and_metadata():
    tmp_dir = Path(tempfile.mkdtemp())
    meta_path = archive_report(b"%PDF-fake-bytes", report_type="country", label="Kenya", output_dir=tmp_dir)
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["report_type"] == "country"
    assert meta["label"] == "Kenya"
    pdf_path = tmp_dir / meta["pdf_filename"]
    assert pdf_path.exists()
    assert pdf_path.read_bytes() == b"%PDF-fake-bytes"
    print("✓ test_archive_report_writes_pdf_and_metadata passed")


def test_list_archived_reports_returns_newest_first():
    tmp_dir = Path(tempfile.mkdtemp())
    archive_report(b"pdf1", report_type="country", label="Kenya", output_dir=tmp_dir)
    archive_report(b"pdf2", report_type="regional", label="East Africa / Horn", output_dir=tmp_dir)
    archive_report(b"pdf3", report_type="custom", label="Some query", output_dir=tmp_dir)

    reports = list_archived_reports(archive_dir=tmp_dir)
    assert len(reports) == 3
    # newest first -- generated_at timestamps should be non-increasing
    timestamps = [r["generated_at"] for r in reports]
    assert timestamps == sorted(timestamps, reverse=True)
    assert {r["report_type"] for r in reports} == {"country", "regional", "custom"}
    print("✓ test_list_archived_reports_returns_newest_first passed")


def test_list_archived_reports_empty_when_no_archive():
    tmp_dir = Path(tempfile.mkdtemp()) / "does_not_exist"
    assert list_archived_reports(archive_dir=tmp_dir) == []
    print("✓ test_list_archived_reports_empty_when_no_archive passed")


def test_list_archived_reports_skips_orphaned_metadata():
    """A metadata JSON whose PDF was deleted (or never written) shouldn't
    surface a broken entry in the archive listing."""
    tmp_dir = Path(tempfile.mkdtemp())
    meta_path = archive_report(b"pdf-bytes", report_type="country", label="Ghana", output_dir=tmp_dir)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    (tmp_dir / meta["pdf_filename"]).unlink()

    reports = list_archived_reports(archive_dir=tmp_dir)
    assert reports == []
    print("✓ test_list_archived_reports_skips_orphaned_metadata passed")


if __name__ == "__main__":
    test_functions = [v for k, v in list(globals().items()) if k.startswith("test_")]
    print(f"Running {len(test_functions)} tests...\n")
    failures = 0
    for test_fn in test_functions:
        try:
            test_fn()
        except AssertionError as e:
            failures += 1
            print(f"✗ {test_fn.__name__} FAILED: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed.")
    if failures:
        sys.exit(1)
