"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { createDocument } from "@/services/api";

export function PasteTextForm() {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const document = await createDocument(text);
      router.push(`/documents/${document.id}`);
    } catch {
      setError("Could not create the document. Is the backend running on port 8000?");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={14}
        required
        placeholder="Paste your raw text here..."
        className="w-full rounded-lg border border-zinc-300 bg-white p-4 font-mono text-sm text-zinc-900 shadow-sm focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
      />
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={submitting || !text.trim()}
        className="self-start rounded-full bg-zinc-900 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        {submitting ? "Creating..." : "Create Document"}
      </button>
    </form>
  );
}
