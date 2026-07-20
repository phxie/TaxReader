import { useEffect, useMemo, useState } from "react";
import {
  deleteDocument,
  documentFileUrl,
  listDocuments,
  syncToSheet,
  updateDocumentStatus,
  uploadDocument,
  type TaxDocument,
} from "./api";

function display(value: string | number | null): string {
  return value === null ? "—" : String(value);
}

function formatAmount(value: number | null): string {
  return value === null ? "—" : `$${value.toFixed(2)}`;
}

const STATUS_STYLES: Record<string, string> = {
  open: "bg-amber-100 text-amber-800 hover:bg-amber-200",
  closed: "bg-gray-100 text-gray-600 hover:bg-gray-200",
};

function StatusPill({ status, onClick }: { status: string; onClick: () => void }) {
  const classes = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600 hover:bg-gray-200";
  return (
    <button
      type="button"
      onClick={onClick}
      title="Click to toggle status"
      className={`inline-block cursor-pointer rounded-full px-2.5 py-0.5 text-xs font-medium capitalize transition-colors ${classes}`}
    >
      {status}
    </button>
  );
}

const SORT_OPTIONS = [
  { value: "uploaded_desc", label: "Upload Date (Newest)" },
  { value: "uploaded_asc", label: "Upload Date (Oldest)" },
  { value: "notice_date_desc", label: "Notice Date (Newest)" },
  { value: "notice_date_asc", label: "Notice Date (Oldest)" },
  { value: "tax_year_desc", label: "Tax Year (Newest)" },
  { value: "tax_year_asc", label: "Tax Year (Oldest)" },
  { value: "amount_due_desc", label: "Amount Due (High to Low)" },
  { value: "amount_due_asc", label: "Amount Due (Low to High)" },
  { value: "status", label: "Status" },
  { value: "filename", label: "Source Document (A–Z)" },
] as const;

type SortValue = (typeof SORT_OPTIONS)[number]["value"];

// Nullable values always sort to the end, regardless of direction.
function compareNullable<T>(a: T | null, b: T | null, compare: (a: T, b: T) => number): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return compare(a, b);
}

function sortDocuments(docs: TaxDocument[], sortBy: SortValue): TaxDocument[] {
  const sorted = [...docs];
  switch (sortBy) {
    case "uploaded_desc":
      return sorted.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
    case "uploaded_asc":
      return sorted.sort((a, b) => a.uploaded_at.localeCompare(b.uploaded_at));
    case "notice_date_desc":
      return sorted.sort((a, b) => compareNullable(a.notice_date, b.notice_date, (x, y) => y.localeCompare(x)));
    case "notice_date_asc":
      return sorted.sort((a, b) => compareNullable(a.notice_date, b.notice_date, (x, y) => x.localeCompare(y)));
    case "tax_year_desc":
      return sorted.sort((a, b) => compareNullable(a.tax_year, b.tax_year, (x, y) => y - x));
    case "tax_year_asc":
      return sorted.sort((a, b) => compareNullable(a.tax_year, b.tax_year, (x, y) => x - y));
    case "amount_due_desc":
      return sorted.sort((a, b) => compareNullable(a.amount_due, b.amount_due, (x, y) => y - x));
    case "amount_due_asc":
      return sorted.sort((a, b) => compareNullable(a.amount_due, b.amount_due, (x, y) => x - y));
    case "status":
      return sorted.sort((a, b) => a.status.localeCompare(b.status));
    case "filename":
      return sorted.sort((a, b) => a.filename.localeCompare(b.filename));
  }
}

export default function App() {
  const [documents, setDocuments] = useState<TaxDocument[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<SortValue>("uploaded_desc");

  const sortedDocuments = useMemo(() => sortDocuments(documents, sortBy), [documents, sortBy]);

  useEffect(() => {
    listDocuments()
      .then(setDocuments)
      .catch((e) => setError(e.message));
  }, []);

  async function handleToggleStatus(doc: TaxDocument) {
    const nextStatus = doc.status === "open" ? "closed" : "open";
    try {
      const updated = await updateDocumentStatus(doc.id, nextStatus);
      setDocuments((prev) => prev.map((d) => (d.id === doc.id ? updated : d)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSync() {
    setIsSyncing(true);
    setError(null);
    setMessage(null);
    try {
      const result = await syncToSheet();
      setDocuments(result.documents);
      setMessage(`Synced ${result.synced} document${result.synced === 1 ? "" : "s"} from Google Sheet.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSyncing(false);
    }
  }

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
    setMessage(null);
    try {
      const fields = await uploadDocument(file);
      setMessage(`${fields.filename} uploaded and added to the Google Sheet. Click "Sync from Google Sheet" to view it here.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <main className="mx-auto max-w-6xl px-4 py-10">
        <header className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">TaxReader</h1>
            <p className="text-sm text-gray-500">Upload tax notices and let Claude extract the details.</p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSync}
              disabled={isSyncing}
              className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium shadow-sm transition-colors ${
                isSyncing
                  ? "cursor-not-allowed border-gray-300 bg-gray-100 text-gray-400"
                  : "border-indigo-600 text-indigo-600 hover:bg-indigo-50"
              }`}
            >
              {isSyncing && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" />
              )}
              {isSyncing ? "Syncing…" : "Sync from Google Sheet"}
            </button>

            <label
              className={`inline-flex cursor-pointer items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors ${
                isUploading ? "cursor-not-allowed bg-gray-400" : "bg-indigo-600 hover:bg-indigo-700"
              }`}
            >
              {isUploading && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              )}
              {isUploading ? "Processing with Claude Haiku…" : "Upload a tax notice PDF"}
              <input
                type="file"
                accept="application/pdf"
                onChange={handleFileChange}
                disabled={isUploading}
                className="hidden"
              />
            </label>
          </div>
        </header>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-6 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            {message}
          </div>
        )}

        <div className="mb-3 flex items-center justify-end gap-2">
          <label htmlFor="sort" className="text-sm text-gray-500">
            Sort by
          </label>
          <select
            id="sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortValue)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                  <th className="px-4 py-3">Source Document</th>
                  <th className="px-4 py-3">Notice Date</th>
                  <th className="px-4 py-3">Tax Year</th>
                  <th className="px-4 py-3">Jurisdiction</th>
                  <th className="px-4 py-3">Issue Summary</th>
                  <th className="px-4 py-3">Amount Due</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {sortedDocuments.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">{doc.filename}</td>
                    <td className="px-4 py-3 text-gray-600">{display(doc.notice_date)}</td>
                    <td className="px-4 py-3 text-gray-600">{display(doc.tax_year)}</td>
                    <td className="px-4 py-3 text-gray-600">{display(doc.jurisdiction)}</td>
                    <td className="px-4 py-3 max-w-xs text-gray-600">{display(doc.issue_summary)}</td>
                    <td className="px-4 py-3 text-gray-600">{formatAmount(doc.amount_due)}</td>
                    <td className="px-4 py-3">
                      <StatusPill status={doc.status} onClick={() => handleToggleStatus(doc)} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <a
                        href={documentFileUrl(doc.id)}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        View
                      </a>{" "}
                      <a
                        href={documentFileUrl(doc.id, true)}
                        className="ml-3 font-medium text-indigo-600 hover:text-indigo-800"
                      >
                        Download
                      </a>{" "}
                      <button
                        type="button"
                        onClick={() => handleDelete(doc)}
                        className="ml-3 font-medium text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {documents.length === 0 && (
            <p className="px-4 py-10 text-center text-sm text-gray-500">
              No documents yet — upload a tax notice PDF to get started.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
