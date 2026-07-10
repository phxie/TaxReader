"""
One-time backfill: scans every PDF currently in the target Drive folder
and processes any not already stored (or changed since last stored).

poller.py only sees changes from the moment its page token is first
created — it does not know about files that were already in the folder
before that point. Run this once (or after adding a large batch of
files outside of the poller's watch) to catch those up:

    uv run backfill.py

Safe to re-run: files whose stored drive_modified_time already matches
Drive are skipped.
"""

import logging
import os

from dotenv import load_dotenv

import db
import drive
from ingest import process_file

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


def main() -> None:
    service_account_file = os.environ["DRIVE_SERVICE_ACCOUNT_FILE"]
    folder_id = os.environ["DRIVE_FOLDER_ID"]
    ocr_engine = os.environ.get("OCR_ENGINE", "easyocr")

    service = drive.get_drive_service(service_account_file)

    with db.get_connection() as conn:
        db.init_schema(conn)

        # Capture a page token before listing (if the poller hasn't
        # already set one), so changes.list picks up anything that
        # changes in the folder during this backfill instead of it
        # falling into the gap between "start of backfill" and
        # "poller's first run".
        if db.get_page_token(conn) is None:
            token = drive.get_start_page_token(service)
            db.set_page_token(conn, token)
            logger.info("Initialized page token for poller.py to resume from")

        files = drive.list_folder_pdfs(service, folder_id)
        logger.info("Found %d PDFs in folder %s", len(files), folder_id)

        processed = 0
        for file in files:
            try:
                if process_file(service, conn, file, ocr_engine):
                    processed += 1
            except Exception:
                logger.exception("Failed to process %s (%s)", file.name, file.id)

        logger.info("Backfill complete: %d/%d files (re)processed", processed, len(files))


if __name__ == "__main__":
    main()
