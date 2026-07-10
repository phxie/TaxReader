"""
Background poller: periodically checks a Google Drive folder for new or
changed PDFs, runs hybrid text extraction on them, and stores the result
in Postgres for the Flask/React dashboard to read.

Run as its own long-lived process, separate from the Flask app:
    uv run poller.py

Required environment variables (see .env.example):
    DRIVE_SERVICE_ACCOUNT_FILE  path to the service account JSON key
    DRIVE_FOLDER_ID             ID of the Drive folder to watch
    DATABASE_URL                Postgres connection string

Optional:
    POLL_INTERVAL_SECONDS       default 300
    OCR_ENGINE                  "easyocr" (default) or "pytesseract"
"""

import logging
import os
import time

from dotenv import load_dotenv

import db
import drive
from ingest import process_file

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("poller")


def run_poll_cycle(service, conn, folder_id: str, ocr_engine: str) -> None:
    page_token = db.get_page_token(conn)
    if page_token is None:
        page_token = drive.get_start_page_token(service)
        db.set_page_token(conn, page_token)
        logger.info("Initialized page token, will only see changes from now on")
        return

    updated_files, removed_ids, next_page_token = drive.poll_changes(service, page_token, folder_id)

    for file_id in removed_ids:
        db.delete_document(conn, file_id)
        logger.info("Removed %s", file_id)

    for file in updated_files:
        try:
            process_file(service, conn, file, ocr_engine)
        except Exception:
            logger.exception("Failed to process %s (%s)", file.name, file.id)

    db.set_page_token(conn, next_page_token)


def main() -> None:
    service_account_file = os.environ["DRIVE_SERVICE_ACCOUNT_FILE"]
    folder_id = os.environ["DRIVE_FOLDER_ID"]
    poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    ocr_engine = os.environ.get("OCR_ENGINE", "easyocr")

    service = drive.get_drive_service(service_account_file)

    with db.get_connection() as conn:
        db.init_schema(conn)

        logger.info("Polling folder %s every %ds", folder_id, poll_interval)
        while True:
            try:
                run_poll_cycle(service, conn, folder_id, ocr_engine)
            except Exception:
                logger.exception("Poll cycle failed")
            time.sleep(poll_interval)


if __name__ == "__main__":
    main()
