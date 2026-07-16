import os
import uuid

from flask import Flask, jsonify, request, send_file
from werkzeug.utils import secure_filename

import db
import extract

TAXDOCS_DIR = os.path.join(os.path.dirname(__file__), "taxdocs")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

os.makedirs(TAXDOCS_DIR, exist_ok=True)
with db.get_connection() as _conn:
    db.init_schema(_conn)


@app.post("/api/documents")
def upload_document():
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "No file provided"}), 400

    pdf_bytes = file.read()
    if not pdf_bytes.startswith(b"%PDF-"):
        return jsonify({"error": "File is not a valid PDF"}), 400

    stored_name = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file_path = os.path.join(TAXDOCS_DIR, stored_name)
    with open(file_path, "wb") as f:
        f.write(pdf_bytes)

    try:
        fields = extract.extract_tax_fields(pdf_bytes, file.filename)
    except Exception as e:
        os.remove(file_path)
        return jsonify({"error": str(e)}), 502

    with db.get_connection() as conn:
        doc_id = db.insert_document(conn, file.filename, file_path, fields)
        document = db.get_document(conn, doc_id)

    return jsonify(document), 201


@app.get("/api/documents")
def list_documents():
    with db.get_connection() as conn:
        return jsonify(db.list_documents(conn))


VALID_STATUSES = {"open", "closed"}


@app.patch("/api/documents/<int:doc_id>")
def update_document_status(doc_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of {sorted(VALID_STATUSES)}"}), 400

    with db.get_connection() as conn:
        if db.get_document(conn, doc_id) is None:
            return jsonify({"error": "Document not found"}), 404

        db.update_status(conn, doc_id, status)
        document = db.get_document(conn, doc_id)

    return jsonify(document)


@app.delete("/api/documents/<int:doc_id>")
def delete_document(doc_id):
    with db.get_connection() as conn:
        document = db.get_document(conn, doc_id)
        if document is None:
            return jsonify({"error": "Document not found"}), 404

        if os.path.exists(document["file_path"]):
            os.remove(document["file_path"])
        db.delete_document(conn, doc_id)

    return "", 204


@app.get("/api/documents/<int:doc_id>/file")
def get_document_file(doc_id):
    with db.get_connection() as conn:
        document = db.get_document(conn, doc_id)

    if document is None or not os.path.exists(document["file_path"]):
        return jsonify({"error": "Document not found"}), 404

    return send_file(
        document["file_path"],
        mimetype="application/pdf",
        as_attachment=request.args.get("download") == "1",
        download_name=document["filename"],
    )


if __name__ == "__main__":
    app.run(port=5000, debug=True)
