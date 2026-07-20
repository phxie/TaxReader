"""
Google Sheets integration: the Sheet is the source of truth for documents.

- Uploading a PDF appends one row directly to the Sheet.
- Clicking "Sync" pulls the Sheet's current contents into the local
  dashboard, fully replacing what's there.

The last two columns (`uploaded_at`, `stored_file`) are internal bookkeeping
so a synced-back row can still be linked to its PDF on disk for View/Download
— `stored_file` is the file's name under `taxdocs/`, not an absolute path
(absolute local paths would be meaningless if the sheet is ever viewed from
another machine).
"""

import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Canonical column order, shared by append (write) and fetch (read) so the
# two can never drift out of sync with each other.
COLUMNS = [
    "filename",
    "notice_date",
    "tax_year",
    "jurisdiction",
    "issue_summary",
    "amount_due",
    "status",
    "uploaded_at",
    "stored_file",
]

HEADERS = [
    "Source Document",
    "Notice Date",
    "Tax Year",
    "Jurisdiction",
    "Issue Summary",
    "Amount Due",
    "Status",
    "Uploaded At",
    "Stored File",
]


def _get_sheets_service():
    service_account_file = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials)


def _ensure_header(service, spreadsheet_id: str, sheet_name: str) -> None:
    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1:A1").execute()
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()


def append_document(filename: str, file_path: str, uploaded_at: str, fields: dict) -> None:
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Sheet1")
    service = _get_sheets_service()

    _ensure_header(service, spreadsheet_id, sheet_name)

    values_map = {
        "filename": filename,
        "notice_date": fields.get("notice_date") or "",
        "tax_year": fields.get("tax_year") if fields.get("tax_year") is not None else "",
        "jurisdiction": fields.get("jurisdiction") or "",
        "issue_summary": fields.get("issue_summary") or "",
        "amount_due": fields.get("amount_due") if fields.get("amount_due") is not None else "",
        "status": "open",
        "uploaded_at": uploaded_at,
        "stored_file": os.path.basename(file_path),
    }
    row = [values_map[column] for column in COLUMNS]

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=sheet_name,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def fetch_documents() -> list[dict]:
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Sheet1")
    service = _get_sheets_service()

    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
    rows = result.get("values", [])
    if not rows:
        return []

    _header, *data_rows = rows
    documents = []
    for row in data_rows:
        row = row + [""] * (len(COLUMNS) - len(row))  # Sheets omits trailing empty cells
        values_map = dict(zip(COLUMNS, row))
        documents.append(
            {
                "filename": values_map["filename"],
                "notice_date": values_map["notice_date"] or None,
                "tax_year": int(values_map["tax_year"]) if values_map["tax_year"] else None,
                "jurisdiction": values_map["jurisdiction"] or None,
                "issue_summary": values_map["issue_summary"] or None,
                "amount_due": float(values_map["amount_due"]) if values_map["amount_due"] else None,
                "status": values_map["status"] or "open",
                "uploaded_at": values_map["uploaded_at"],
                "stored_file": values_map["stored_file"],
            }
        )
    return documents
