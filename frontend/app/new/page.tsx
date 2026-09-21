"use client";

import { ClipboardPaste, Upload } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { FileUploadForm } from "@/components/FileUploadForm";
import { PasteTextForm } from "@/components/PasteTextForm";

type Mode = "paste" | "upload";

function tabClass(active: boolean): string {
  return `flex flex-1 items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium transition-colors ${
    active
      ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-50"
      : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
  }`;
}

function NewDocumentContent() {
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<Mode>(searchParams.get("mode") === "upload" ? "upload" : "paste");

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">Create a document</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Paste raw text or upload a file &mdash; either way, the system turns it into a structured
          document you can then edit.
        </p>
      </div>

      <div className="flex gap-1 rounded-xl bg-zinc-100 p-1 dark:bg-zinc-900">
        <button type="button" onClick={() => setMode("paste")} className={tabClass(mode === "paste")}>
          <ClipboardPaste className="h-4 w-4" aria-hidden="true" />
          Paste text
        </button>
        <button type="button" onClick={() => setMode("upload")} className={tabClass(mode === "upload")}>
          <Upload className="h-4 w-4" aria-hidden="true" />
          Upload file
        </button>
      </div>

      {mode === "paste" ? <PasteTextForm /> : <FileUploadForm />}
    </main>
  );
}

export default function NewDocumentPage() {
  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <Suspense fallback={null}>
        <NewDocumentContent />
      </Suspense>
    </div>
  );
}
