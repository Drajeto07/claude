import { FileDown } from "lucide-react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Plain <a> downloads, not a fetch+blob dance -- a GET request with a
 * Content-Disposition: attachment header is all a browser needs to save the
 * file, and this needs no JS beyond the href itself. Sized for AppHeader's
 * rightSlot.
 */
export function ExportPanel({ documentId }: { documentId: string }) {
  return (
    <div className="flex items-center gap-2">
      <a
        href={`${API_BASE_URL}/api/documents/${documentId}/export/docx`}
        className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-300"
      >
        <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
        DOCX
      </a>
      <a
        href={`${API_BASE_URL}/api/documents/${documentId}/export/pdf`}
        className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:border-accent hover:text-accent dark:border-zinc-700 dark:text-zinc-300"
      >
        <FileDown className="h-3.5 w-3.5" aria-hidden="true" />
        PDF
      </a>
    </div>
  );
}
