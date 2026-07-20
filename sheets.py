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

VALID_STATUSES = ["open", "closed"]


def _get_sheets_service():
    service_account_file = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
    credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    return build("sheets", "v4", credentials=credentials)


def _get_sheet_id(service, spreadsheet_id: str, sheet_name: str) -> int:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == sheet_name)


def _apply_status_dropdown(service, spreadsheet_id: str, sheet_name: str) -> None:
    """Restrict the Status column (below the header) to a dropdown of VALID_STATUSES.
    The range's endRowIndex is left unbounded so rows appended later are covered too."""
    sheet_id = _get_sheet_id(service, spreadsheet_id, sheet_name)
    status_column = COLUMNS.index("status")

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # skip header row
                            "startColumnIndex": status_column,
                            "endColumnIndex": status_column + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [{"userEnteredValue": status} for status in VALID_STATUSES],
                            },
                            "showCustomUi": True,
                            "strict": True,
                        },
                    }
                }
            ]
        },
    ).execute()


def _ensure_header(service, spreadsheet_id: str, sheet_name: str) -> None:
    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1:A1").execute()
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [HEADERS]},
        ).execute()
    _apply_status_dropdown(service, spreadsheet_id, sheet_name)


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


def _find_row_index(service, spreadsheet_id: str, sheet_name: str, filename: str, stored_file: str) -> int | None:
    """0-indexed row position (including the header row) of the first matching document,
    or None if not found. Matches by stored_file when available (unique per upload);
    falls back to filename for legacy rows written before that column existed."""
    result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
    rows = result.get("values", [])
    for i, row in enumerate(rows):
        if i == 0:
            continue  # header
        row = row + [""] * (len(COLUMNS) - len(row))
        values_map = dict(zip(COLUMNS, row))
        if stored_file:
            if values_map["stored_file"] == stored_file:
                return i
        elif values_map["filename"] == filename:
            return i
    return None


def update_status(filename: str, stored_file: str, status: str) -> None:
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Sheet1")
    service = _get_sheets_service()

    row_index = _find_row_index(service, spreadsheet_id, sheet_name, filename, stored_file)
    if row_index is None:
        raise ValueError(f"{filename!r} not found in the sheet")

    status_column = chr(ord("A") + COLUMNS.index("status"))
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!{status_column}{row_index + 1}",
        valueInputOption="RAW",
        body={"values": [[status]]},
    ).execute()


def delete_document(filename: str, stored_file: str) -> None:
    spreadsheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheet_name = os.environ.get("GOOGLE_SHEET_NAME", "Sheet1")
    service = _get_sheets_service()

    row_index = _find_row_index(service, spreadsheet_id, sheet_name, filename, stored_file)
    if row_index is None:
        raise ValueError(f"{filename!r} not found in the sheet")

    sheet_id = _get_sheet_id(service, spreadsheet_id, sheet_name)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "deleteDimension": {
                        "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": row_index, "endIndex": row_index + 1}
                    }
                }
            ]
        },
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
