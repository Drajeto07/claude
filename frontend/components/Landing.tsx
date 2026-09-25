import Link from "next/link";
import { ClipboardPaste, ShieldCheck, Upload } from "lucide-react";

import { AppHeader } from "@/components/AppHeader";

/** The public home page, for someone not signed in. */
export function Landing() {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="flex max-w-xl flex-col items-center gap-6 text-center">
          <h1 className="text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">SmartDoc Formatter</h1>
          <p className="text-lg leading-8 text-zinc-600 dark:text-zinc-400">
            Paste raw text and get it back as a structured, editable document &mdash; no manual font/size/spacing fiddling.
          </p>
        </div>

        <div className="mt-10 grid w-full max-w-2xl gap-4 sm:grid-cols-2">
          <Link
            href="/new"
            className="group flex flex-col items-start gap-3 rounded-2xl border border-zinc-200 bg-white p-6 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-accent hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900"
          >
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent/10 text-accent">
              <ClipboardPaste className="h-5 w-5" aria-hidden="true" />
            </span>
            <span>
              <span className="block text-base font-semibold text-zinc-900 dark:text-zinc-50">Paste text</span>
              <span className="mt-1 block text-sm text-zinc-500 dark:text-zinc-400">
                Drop in raw text and let structure analysis figure out headings, lists and tables.
              </span>
            </span>
          </Link>

          <Link
            href="/new?mode=upload"
            className="group flex flex-col items-start gap-3 rounded-2xl border border-zinc-200 bg-white p-6 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-accent hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900"
          >
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent/10 text-accent">
              <Upload className="h-5 w-5" aria-hidden="true" />
            </span>
            <span>
              <span className="block text-base font-semibold text-zinc-900 dark:text-zinc-50">Upload a file</span>
              <span className="mt-1 block text-sm text-zinc-500 dark:text-zinc-400">TXT, DOCX or PDF &mdash; real styles/tables come along for DOCX uploads.</span>
            </span>
          </Link>
        </div>

        <p className="mt-8 flex max-w-2xl items-start gap-2 text-left text-sm text-zinc-600 dark:text-zinc-400">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
          <span>
            Your documents are private to your account. The AI only reads what a task needs and never rewrites your words, and deleting a
            document deletes it for good, with its history.
          </span>
        </p>

        <p className="mt-6 flex gap-4 text-sm">
          <Link href="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
          <Link href="/register" className="font-medium text-accent hover:underline">
            Create an account
          </Link>
        </p>
      </main>
    </div>
  );
}
