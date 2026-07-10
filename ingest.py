"""
Shared per-file ingestion logic used by both poller.py (incremental,
via the Drive changes feed) and backfill.py (one-time full folder
scan): download a PDF, run hybrid extraction, and upsert the result.
"""

import logging
import os
import sqlite3
import tempfile

import db
import drive
from extraction import combine_results, extract_pdf_hybrid

logger = logging.getLogger(__name__)


def process_file(service, conn: sqlite3.Connection, file: drive.DriveFile, ocr_engine: str) -> bool:
    """Download, extract, and store one file. Returns False if skipped
    because its Drive modifiedTime already matches what's stored."""
    stored_modified_time = db.get_document_modified_time(conn, file.id)
    if stored_modified_time is not None and stored_modified_time == file.modified_time:
        return False

    logger.info("Processing %s (%s)", file.name, file.id)
    pdf_bytes = drive.download_file(service, file.id)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        page_results = extract_pdf_hybrid(tmp_path, ocr_engine=ocr_engine)
        text = combine_results(page_results)
    finally:
        os.remove(tmp_path)

    db.upsert_document(conn, file.id, file.name, text, file.modified_time)
    logger.info("Stored %s (%d pages)", file.name, len(page_results))
    return True
