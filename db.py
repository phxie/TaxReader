"""
SQLite storage for extracted tax documents.

Two tables:
- documents: one row per Drive file, upserted by drive_file_id so
  re-processing the same file (e.g. after a rename) updates in place.
- sync_state: a single key/value row holding the Drive changes API
  page token, so the poller can resume from where it left off after
  a restart instead of re-scanning the whole folder.

WAL mode is enabled so the poller (writer) and a Flask dashboard
(reader) can access the database concurrently without lock errors.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    drive_file_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    drive_modified_time TEXT,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

PAGE_TOKEN_KEY = "drive_changes_page_token"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    db_path = os.environ.get("DB_PATH", "taxreader.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_page_token(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key = ?", (PAGE_TOKEN_KEY,)
    ).fetchone()
    return row[0] if row else None


def set_page_token(conn: sqlite3.Connection, token: str) -> None:
    conn.execute(
        """
        INSERT INTO sync_state (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (PAGE_TOKEN_KEY, token),
    )
    conn.commit()


def get_document_modified_time(conn: sqlite3.Connection, drive_file_id: str) -> Optional[datetime]:
    row = conn.execute(
        "SELECT drive_modified_time FROM documents WHERE drive_file_id = ?",
        (drive_file_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return datetime.fromisoformat(row[0])


def upsert_document(
    conn: sqlite3.Connection,
    drive_file_id: str,
    name: str,
    text: str,
    drive_modified_time: Optional[datetime],
) -> None:
    conn.execute(
        """
        INSERT INTO documents (drive_file_id, name, text, drive_modified_time, processed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(drive_file_id) DO UPDATE SET
            name = excluded.name,
            text = excluded.text,
            drive_modified_time = excluded.drive_modified_time,
            processed_at = excluded.processed_at
        """,
        (
            drive_file_id,
            name,
            text,
            drive_modified_time.isoformat() if drive_modified_time else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def delete_document(conn: sqlite3.Connection, drive_file_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE drive_file_id = ?", (drive_file_id,))
    conn.commit()
