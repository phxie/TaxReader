import { useEffect, useState } from "react";
import { deleteDocument, documentFileUrl, listDocuments, uploadDocument, type TaxDocument } from "./api";

function display(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

function formatAmount(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

export default function App() {
  const [documents, setDocuments] = useState<TaxDocument[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch((e) => setError(e.message));
  }, []);

  async function handleDelete(doc: TaxDocument) {
    if (!window.confirm(`Delete ${doc.filename}? This cannot be undone.`)) return;

    try {
      await deleteDocument(doc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    setIsUploading(true);
    setError(null);
    try {
      const document = await uploadDocument(file);
      setDocuments((prev) => [document, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <main>
      <h1>TaxReader</h1>

      <label className="upload-button">
        {isUploading ? "Processing with Claude Haiku…" : "Upload a tax notice PDF"}
        <input
          type="file"
          accept="application/pdf"
          onChange={handleFileChange}
          disabled={isUploading}
        />
      </label>

      {error && <p className="error">{error}</p>}

      <table>
        <thead>
          <tr>
            <th>Source Document</th>
            <th>Notice Date</th>
            <th>Tax Year</th>
            <th>Jurisdiction</th>
            <th>Issue Summary</th>
            <th>Amount Due</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr key={doc.id}>
              <td>{doc.filename}</td>
              <td>{display(doc.notice_date)}</td>
              <td>{display(doc.tax_year)}</td>
              <td>{display(doc.jurisdiction)}</td>
              <td>{display(doc.issue_summary)}</td>
              <td>{formatAmount(doc.amount_due)}</td>
              <td>{doc.status}</td>
              <td>
                <a href={documentFileUrl(doc.id)} target="_blank" rel="noreferrer">
                  View
                </a>{" "}
                <a href={documentFileUrl(doc.id, true)}>Download</a>{" "}
                <button type="button" onClick={() => handleDelete(doc)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
