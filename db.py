"""
SQLite storage for uploaded tax notice PDFs and their Claude-extracted
fields. Each upload is a new row (no dedup/upsert needed).

WAL mode is enabled so the Flask app can read and write concurrently
without lock errors.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    notice_date TEXT,
    tax_year INTEGER,
    jurisdiction TEXT,
    issue_summary TEXT,
    amount_due REAL,
    status TEXT NOT NULL DEFAULT 'open'
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    db_path = os.environ.get("DB_PATH", "taxreader.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def insert_document(conn: sqlite3.Connection, filename: str, file_path: str, fields: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO documents
            (filename, file_path, uploaded_at, notice_date, tax_year, jurisdiction, issue_summary, amount_due, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """,
        (
            filename,
            file_path,
            datetime.now(timezone.utc).isoformat(),
            fields.get("notice_date"),
            fields.get("tax_year"),
            fields.get("jurisdiction"),
            fields.get("issue_summary"),
            fields.get("amount_due"),
        ),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()
    return [dict(row) for row in rows]


def get_document(conn: sqlite3.Connection, doc_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def delete_document(conn: sqlite3.Connection, doc_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
