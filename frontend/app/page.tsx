import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center bg-zinc-50 px-6 dark:bg-black">
      <main className="flex max-w-xl flex-col items-center gap-6 text-center">
        <h1 className="text-4xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          SmartDoc Formatter
        </h1>
        <p className="text-lg leading-8 text-zinc-600 dark:text-zinc-400">
          Paste raw text and get it back as a structured, editable document &mdash; no manual
          font/size/spacing fiddling.
        </p>
        <Link
          href="/new"
          className="rounded-full bg-zinc-900 px-8 py-3 text-sm font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          New Document
        </Link>
      </main>
    </div>
  );
}
