export interface TaxDocument {
  id: number;
  filename: string;
  file_path: string;
  uploaded_at: string;
  notice_date: string | null;
  tax_year: number | null;
  jurisdiction: string | null;
  issue_summary: string | null;
  amount_due: number | null;
  status: string;
}

export async function listDocuments(): Promise<TaxDocument[]> {
  const res = await fetch("/api/documents");
  if (!res.ok) throw new Error(`Failed to list documents: ${res.status}`);
  return res.json();
}

export async function uploadDocument(file: File): Promise<TaxDocument> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch("/api/documents", { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Upload failed: ${res.status}`);
  }
  return res.json();
}

export function documentFileUrl(id: number, download = false): string {
  return `/api/documents/${id}/file${download ? "?download=1" : ""}`;
}

export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`/api/documents/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `Delete failed: ${res.status}`);
  }
}
