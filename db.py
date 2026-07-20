"""
SQLite storage for the dashboard's local view of the documents tracked in
the Google Sheet. The Sheet is the source of truth: `replace_all_documents`
is how a "Sync" pull replaces the local table wholesale with the Sheet's
current contents. Uploads no longer write here directly — they write to the
Sheet (see `sheets.py`), and only show up locally after the next sync.

WAL mode is enabled so the Flask app can read and write concurrently
without lock errors.
"""

import sqlite3
import os
from contextlib import contextmanager
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


def replace_all_documents(conn: sqlite3.Connection, documents: list[dict]) -> None:
    """Wholesale replace the local table with rows pulled from the Google Sheet."""
    conn.execute("DELETE FROM documents")
    conn.executemany(
        """
        INSERT INTO documents
            (filename, file_path, uploaded_at, notice_date, tax_year, jurisdiction, issue_summary, amount_due, status)
        VALUES (:filename, :file_path, :uploaded_at, :notice_date, :tax_year, :jurisdiction, :issue_summary, :amount_due, :status)
        """,
        documents,
    )
    conn.commit()


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()
    return [dict(row) for row in rows]


def get_document(conn: sqlite3.Connection, doc_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def delete_document(conn: sqlite3.Connection, doc_id: int) -> None:
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()


def update_status(conn: sqlite3.Connection, doc_id: int, status: str) -> None:
    conn.execute("UPDATE documents SET status = ? WHERE id = ?", (status, doc_id))
    conn.commit()
