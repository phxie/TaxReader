"""
Google Sheets sync: pushes the current documents table to a configured
Google Sheet, fully overwriting its contents on every sync.
"""

import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADERS = ["Source Document", "Notice Date", "Tax Year", "Jurisdiction", "Issue Summary", "Amount Due", "Status"]


def _get_sheets_service():
    service_account_file = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials)


def sync_documents(documents: list[dict]) -> int:
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Sheet1")

    rows = [HEADERS] + [
        [
            doc["filename"],
            doc["notice_date"] or "",
            doc["tax_year"] if doc["tax_year"] is not None else "",
            doc["jurisdiction"] or "",
            doc["issue_summary"] or "",
            doc["amount_due"] if doc["amount_due"] is not None else "",
            doc["status"],
        ]
        for doc in documents
    ]

    values = _get_sheets_service().spreadsheets().values()
    values.clear(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
    values.update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()

    return len(documents)
