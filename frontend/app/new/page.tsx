import { FileUploadForm } from "@/components/FileUploadForm";
import { PasteTextForm } from "@/components/PasteTextForm";

export default function NewDocumentPage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Create a document</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Paste raw text or upload a file &mdash; either way, the system turns it into a structured
          document you can then edit.
        </p>
      </div>
      <PasteTextForm />
      <div className="flex items-center gap-4 text-xs uppercase tracking-wide text-zinc-400">
        <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
        or
        <div className="h-px flex-1 bg-zinc-200 dark:bg-zinc-800" />
      </div>
      <FileUploadForm />
    </main>
  );
}
