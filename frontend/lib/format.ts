const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

/** "just now", "5 min ago", "3 h ago", "yesterday", then the date. */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)} h ago`;
  if (seconds < 2 * 86_400) return "yesterday";
  return dateOnly.format(then);
}

/** The full date and time, e.g. for a tooltip. */
export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

const SOURCES: Record<string, string> = {
  pasted_text: "Pasted text",
  uploaded_docx: "Word file",
  uploaded_pdf: "PDF",
  uploaded_txt: "Text file",
};

/** Where a document came from (DocumentMetadata.sourceType), in words. */
export function sourceLabel(sourceType: string): string {
  return SOURCES[sourceType] ?? "Other";
}
