"""
Shared pytest fixtures for the Flask app test suite.

Sets dummy credentials before `app` (and the `extract`/`sheets` modules it
imports) are ever loaded, so the suite never depends on a real .env file or
makes real Anthropic/Google API calls. Each test gets its own throwaway
SQLite DB and taxdocs/ directory so tests can't see each other's data or
touch the real project files.
"""

import os
import tempfile

os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")
os.environ.setdefault("GOOGLE_SHEET_ID", "test-sheet-id")
# Keeps app.py's module-level `db.init_schema()` call (which runs once,
# at import time, before any per-test fixture below has a chance to
# override DB_PATH) from ever touching the real project's taxreader.db.
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "taxreader_test_import.db"))

import pytest

import app as app_module
import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A Flask test client backed by an isolated, throwaway DB and taxdocs dir."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))

    taxdocs_dir = tmp_path / "taxdocs"
    taxdocs_dir.mkdir()
    monkeypatch.setattr(app_module, "TAXDOCS_DIR", str(taxdocs_dir))

    with db.get_connection() as conn:
        db.init_schema(conn)

    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()
