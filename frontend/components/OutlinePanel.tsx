"use client";

import type { Element } from "@/types/document";

function scrollToElement(id: string) {
  document.querySelector(`[data-element-id="${id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function OutlinePanel({ elements }: { elements: Element[] }) {
  const headings = elements.filter((el) => el.type === "heading").sort((a, b) => a.order - b.order);
  if (headings.length === 0) return null;

  return (
    <nav className="sticky top-6 rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">Outline</h2>
      <ul className="flex flex-col gap-1">
        {headings.map((heading) => (
          <li key={heading.id} style={{ paddingLeft: `${((heading.level ?? 1) - 1) * 12}px` }}>
            <button
              type="button"
              onClick={() => scrollToElement(heading.id)}
              className="text-left text-zinc-600 hover:text-zinc-900 hover:underline dark:text-zinc-400 dark:hover:text-zinc-100"
            >
              {heading.content || "(untitled)"}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
