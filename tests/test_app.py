"""
Unit tests for app.py's Flask routes.

Every call into extract.py (Claude) and sheets.py (Google Sheets) is mocked
via monkeypatch — these are unit tests for the Flask routing/orchestration
logic, not integration tests, and must never make real network calls or
cost real API usage.
"""

import os
from io import BytesIO

import db

FAKE_PDF_BYTES = b"%PDF-1.4\nfake pdf content for testing\n%%EOF"

FAKE_FIELDS = {
    "notice_date": "2023-04-15",
    "tax_year": 2023,
    "jurisdiction": "IRS",
    "issue_summary": "Test notice summary.",
    "amount_due": 500.0,
}


def seed_document(conn, **overrides):
    doc = {
        "filename": "existing.pdf",
        "file_path": "",
        "uploaded_at": "2024-01-01T00:00:00+00:00",
        "notice_date": "2023-04-15",
        "tax_year": 2023,
        "jurisdiction": "IRS",
        "issue_summary": "Existing summary.",
        "amount_due": 250.0,
        "status": "open",
    }
    doc.update(overrides)
    db.replace_all_documents(conn, [doc])
    with db.get_connection() as fresh:
        return db.list_documents(fresh)[0]


def raiser(message):
    def _raise(*args, **kwargs):
        raise RuntimeError(message)

    return _raise


# --- POST /api/documents (upload) ---


def test_upload_document_success(client, monkeypatch):
    calls = {}

    def fake_extract(pdf_bytes, filename):
        calls["extract"] = (pdf_bytes, filename)
        return dict(FAKE_FIELDS)

    def fake_append(filename, file_path, uploaded_at, fields):
        calls["append"] = (filename, file_path, uploaded_at, fields)

    monkeypatch.setattr("app.extract.extract_tax_fields", fake_extract)
    monkeypatch.setattr("app.sheets.append_document", fake_append)

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(FAKE_PDF_BYTES), "notice.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["filename"] == "notice.pdf"
    assert body["tax_year"] == 2023
    assert "id" not in body  # upload writes to the Sheet only, not the local DB

    assert calls["extract"] == (FAKE_PDF_BYTES, "notice.pdf")
    append_filename, append_path, _uploaded_at, append_fields = calls["append"]
    assert append_filename == "notice.pdf"
    assert os.path.exists(append_path)
    assert append_fields == FAKE_FIELDS


def test_upload_document_missing_file(client):
    response = client.post("/api/documents", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_upload_document_rejects_non_pdf_without_calling_apis(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.extract.extract_tax_fields", lambda *a, **k: calls.append("extract"))
    monkeypatch.setattr("app.sheets.append_document", lambda *a, **k: calls.append("append"))

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(b"not a pdf"), "notice.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert calls == []  # never burns an API call on garbage input


def test_upload_document_extraction_failure_cleans_up_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.extract.extract_tax_fields", raiser("extraction failed"))
    append_calls = []
    monkeypatch.setattr("app.sheets.append_document", lambda *a, **k: append_calls.append(1))

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(FAKE_PDF_BYTES), "notice.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 502
    assert append_calls == []
    assert os.listdir(tmp_path / "taxdocs") == []  # no orphaned file left behind


def test_upload_document_sheet_failure_cleans_up_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.extract.extract_tax_fields", lambda *a, **k: dict(FAKE_FIELDS))
    monkeypatch.setattr("app.sheets.append_document", raiser("sheets unavailable"))

    response = client.post(
        "/api/documents",
        data={"file": (BytesIO(FAKE_PDF_BYTES), "notice.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 502
    assert os.listdir(tmp_path / "taxdocs") == []


# --- GET /api/documents (list) ---


def test_list_documents_empty(client):
    response = client.get("/api/documents")
    assert response.status_code == 200
    assert response.get_json() == []


def test_list_documents_returns_seeded_rows(client):
    with db.get_connection() as conn:
        seed_document(conn, filename="a.pdf")

    response = client.get("/api/documents")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body) == 1
    assert body[0]["filename"] == "a.pdf"


# --- POST /api/documents/sync-sheet ---


def test_sync_sheet_replaces_local_state(client, monkeypatch):
    with db.get_connection() as conn:
        seed_document(conn, filename="stale.pdf")

    sheet_rows = [
        {
            "filename": "fresh.pdf",
            "notice_date": "2023-01-01",
            "tax_year": 2023,
            "jurisdiction": "IRS",
            "issue_summary": "Fresh from the sheet.",
            "amount_due": 42.0,
            "status": "open",
            "uploaded_at": "2024-06-01T00:00:00+00:00",
            "stored_file": "abc123_fresh.pdf",
        }
    ]
    monkeypatch.setattr("app.sheets.fetch_documents", lambda: sheet_rows)

    response = client.post("/api/documents/sync-sheet")
    assert response.status_code == 200
    body = response.get_json()
    assert body["synced"] == 1
    assert len(body["documents"]) == 1
    doc = body["documents"][0]
    assert doc["filename"] == "fresh.pdf"
    assert doc["file_path"].endswith("abc123_fresh.pdf")

    # stale.pdf from before the sync must be gone
    filenames = {d["filename"] for d in client.get("/api/documents").get_json()}
    assert filenames == {"fresh.pdf"}


def test_sync_sheet_empty_stored_file_yields_empty_file_path(client, monkeypatch):
    sheet_rows = [
        {
            "filename": "legacy.pdf",
            "notice_date": None,
            "tax_year": None,
            "jurisdiction": None,
            "issue_summary": None,
            "amount_due": None,
            "status": "open",
            "uploaded_at": "",
            "stored_file": "",
        }
    ]
    monkeypatch.setattr("app.sheets.fetch_documents", lambda: sheet_rows)

    response = client.post("/api/documents/sync-sheet")
    assert response.status_code == 200
    assert response.get_json()["documents"][0]["file_path"] == ""


def test_sync_sheet_failure(client, monkeypatch):
    monkeypatch.setattr("app.sheets.fetch_documents", raiser("sheets unavailable"))
    response = client.post("/api/documents/sync-sheet")
    assert response.status_code == 502


# --- PATCH /api/documents/<id> (status toggle) ---


def test_update_status_success(client, monkeypatch):
    with db.get_connection() as conn:
        doc = seed_document(conn, status="open")

    calls = []
    monkeypatch.setattr("app.sheets.update_status", lambda *a: calls.append(a))

    response = client.patch(f"/api/documents/{doc['id']}", json={"status": "closed"})

    assert response.status_code == 200
    assert response.get_json()["status"] == "closed"
    assert calls == [(doc["filename"], "", "closed")]


def test_update_status_invalid_value_rejected(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.sheets.update_status", lambda *a: calls.append(a))

    with db.get_connection() as conn:
        doc = seed_document(conn)

    response = client.patch(f"/api/documents/{doc['id']}", json={"status": "bogus"})

    assert response.status_code == 400
    assert calls == []


def test_update_status_not_found(client):
    response = client.patch("/api/documents/999", json={"status": "closed"})
    assert response.status_code == 404


def test_update_status_sheet_failure_leaves_local_state_untouched(client, monkeypatch):
    with db.get_connection() as conn:
        doc = seed_document(conn, status="open")

    monkeypatch.setattr("app.sheets.update_status", raiser("sheets unavailable"))

    response = client.patch(f"/api/documents/{doc['id']}", json={"status": "closed"})

    assert response.status_code == 502
    with db.get_connection() as conn:
        assert db.get_document(conn, doc["id"])["status"] == "open"  # unchanged


# --- DELETE /api/documents/<id> ---


def test_delete_document_success(client, monkeypatch, tmp_path):
    file_path = tmp_path / "taxdocs" / "somefile.pdf"
    file_path.write_bytes(FAKE_PDF_BYTES)

    with db.get_connection() as conn:
        doc = seed_document(conn, file_path=str(file_path))

    calls = []
    monkeypatch.setattr("app.sheets.delete_document", lambda *a: calls.append(a))

    response = client.delete(f"/api/documents/{doc['id']}")

    assert response.status_code == 204
    assert calls == [(doc["filename"], "somefile.pdf")]
    assert not file_path.exists()
    with db.get_connection() as conn:
        assert db.get_document(conn, doc["id"]) is None


def test_delete_document_not_found(client):
    response = client.delete("/api/documents/999")
    assert response.status_code == 404


def test_delete_document_sheet_failure_leaves_local_state_untouched(client, monkeypatch, tmp_path):
    file_path = tmp_path / "taxdocs" / "somefile.pdf"
    file_path.write_bytes(FAKE_PDF_BYTES)

    with db.get_connection() as conn:
        doc = seed_document(conn, file_path=str(file_path))

    monkeypatch.setattr("app.sheets.delete_document", raiser("sheets unavailable"))

    response = client.delete(f"/api/documents/{doc['id']}")

    assert response.status_code == 502
    assert file_path.exists()  # file not removed
    with db.get_connection() as conn:
        assert db.get_document(conn, doc["id"]) is not None  # row not removed


# --- GET /api/documents/<id>/file ---


def test_get_document_file_success(client, tmp_path):
    file_path = tmp_path / "taxdocs" / "somefile.pdf"
    file_path.write_bytes(FAKE_PDF_BYTES)

    with db.get_connection() as conn:
        doc = seed_document(conn, file_path=str(file_path), filename="somefile.pdf")

    response = client.get(f"/api/documents/{doc['id']}/file")

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data == FAKE_PDF_BYTES


def test_get_document_file_not_found(client):
    response = client.get("/api/documents/999/file")
    assert response.status_code == 404


def test_get_document_file_missing_on_disk(client):
    with db.get_connection() as conn:
        doc = seed_document(conn, file_path="/nonexistent/path.pdf")

    response = client.get(f"/api/documents/{doc['id']}/file")
    assert response.status_code == 404
