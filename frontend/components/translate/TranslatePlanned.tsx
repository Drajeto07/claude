"use client";

import { ArrowLeft, Clock3, Languages } from "lucide-react";
import Link from "next/link";

import { useI18n } from "@/i18n/I18nProvider";

/**
 * The Translate entry (UI review 2026-10-14, task S2-070): until the shared translation engine of
 * phase P7 is wired here, this page says what the flow will be and that it isn't available yet.
 * It translates nothing and pretends nothing.
 */
export function TranslatePlanned() {
  const { m } = useI18n();
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-8 px-4 py-10 sm:px-8">
      <header className="flex flex-col gap-3">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-tile-rose text-tile-rose-ink">
          <Languages className="h-6 w-6" aria-hidden="true" />
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{m.translate.title}</h1>
        <p className="text-sm text-muted">{m.translate.subtitle}</p>
      </header>

      <div role="status" className="flex items-start gap-3 rounded-2xl border border-line bg-surface p-4">
        <Clock3 className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden="true" />
        <p className="text-sm text-foreground">
          <span className="font-semibold">{m.translate.status}.</span> {m.translate.statusNote}
        </p>
      </div>

      <section aria-labelledby="translate-steps" className="flex flex-col gap-4">
        <h2 id="translate-steps" className="text-base font-semibold text-foreground">
          {m.translate.stepsTitle}
        </h2>
        <ol className="grid gap-3 sm:grid-cols-2">
          {m.translate.steps.map((step, index) => (
            <li key={step.title} className="flex gap-3 rounded-2xl bg-surface p-4 shadow-card">
              <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent">
                {index + 1}
              </span>
              <span>
                <span className="block text-sm font-semibold text-foreground">{step.title}</span>
                <span className="mt-0.5 block text-xs text-muted">{step.text}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <Link href="/" className="flex w-fit items-center gap-1.5 rounded text-sm font-medium text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {m.translate.back}
      </Link>
    </main>
  );
}
