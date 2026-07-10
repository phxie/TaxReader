"""
Google Drive access for the poller: service-account auth, incremental
change listing via the Changes API, and file download.

Using changes.list (rather than re-listing the folder every poll) means
each poll only costs an API call proportional to what actually changed,
and the page token lets the poller resume correctly across restarts.
"""

import io
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
PDF_MIME_TYPE = "application/pdf"

CHANGE_FIELDS = (
    "newStartPageToken,nextPageToken,"
    "changes(fileId,removed,file(id,name,mimeType,parents,trashed,modifiedTime))"
)


@dataclass
class DriveFile:
    id: str
    name: str
    modified_time: Optional[datetime]


def get_drive_service(service_account_file: str) -> Resource:
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES
    )
    return build("drive", "v3", credentials=credentials)


def get_start_page_token(service: Resource) -> str:
    """Fetch a fresh page token, used the first time the poller runs."""
    response = service.changes().getStartPageToken().execute()
    return response["startPageToken"]


def _parse_modified_time(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def poll_changes(
    service: Resource, page_token: str, folder_id: str
) -> tuple[List[DriveFile], List[str], str]:
    """
    Fetch all changes since page_token, filtered to PDFs currently inside
    folder_id.

    Returns (new_or_updated_files, removed_or_trashed_file_ids, next_page_token).
    """
    updated: List[DriveFile] = []
    removed: List[str] = []
    token = page_token

    while token is not None:
        response = (
            service.changes()
            .list(pageToken=token, fields=CHANGE_FIELDS, includeRemoved=True)
            .execute()
        )

        for change in response.get("changes", []):
            file_id = change["fileId"]

            if change.get("removed"):
                removed.append(file_id)
                continue

            file = change.get("file")
            if file is None:
                continue

            if file.get("trashed"):
                removed.append(file_id)
                continue

            if file.get("mimeType") != PDF_MIME_TYPE:
                continue

            if folder_id not in (file.get("parents") or []):
                continue

            updated.append(
                DriveFile(
                    id=file["id"],
                    name=file["name"],
                    modified_time=_parse_modified_time(file.get("modifiedTime")),
                )
            )

        token = response.get("nextPageToken")
        if "newStartPageToken" in response:
            next_start_token = response["newStartPageToken"]

    return updated, removed, next_start_token


def list_folder_pdfs(service: Resource, folder_id: str) -> List[DriveFile]:
    """List every non-trashed PDF currently inside folder_id (single level, not recursive)."""
    query = f"'{folder_id}' in parents and mimeType='{PDF_MIME_TYPE}' and trashed=false"
    files: List[DriveFile] = []
    page_token: Optional[str] = None

    while True:
        response = (
            service.files()
            .list(q=query, fields="nextPageToken, files(id,name,modifiedTime)", pageToken=page_token, pageSize=1000)
            .execute()
        )
        for file in response.get("files", []):
            files.append(
                DriveFile(
                    id=file["id"],
                    name=file["name"],
                    modified_time=_parse_modified_time(file.get("modifiedTime")),
                )
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def download_file(service: Resource, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()
