const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Plain <a> downloads, not a fetch+blob dance -- a GET request with a
 * Content-Disposition: attachment header is all a browser needs to save the
 * file, and this needs no JS beyond the href itself.
 */
export function ExportPanel({ documentId }: { documentId: string }) {
  return (
    <div className="mb-6 flex items-center gap-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900/50">
      <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Export</h2>
      <a
        href={`${API_BASE_URL}/api/documents/${documentId}/export/docx`}
        className="rounded-full border border-zinc-300 px-4 py-1.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        Export as DOCX
      </a>
      <a
        href={`${API_BASE_URL}/api/documents/${documentId}/export/pdf`}
        className="rounded-full border border-zinc-300 px-4 py-1.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        Export as PDF
      </a>
    </div>
  );
}
