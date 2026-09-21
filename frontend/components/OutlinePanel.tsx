"use client";

import type { Element } from "@/types/document";

function scrollToElement(id: string) {
  document.querySelector(`[data-element-id="${id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function OutlinePanel({ elements }: { elements: Element[] }) {
  const headings = elements.filter((el) => el.type === "heading").sort((a, b) => a.order - b.order);
  if (headings.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">No headings yet.</p>;
  }

  return (
    <nav>
      <ul className="flex flex-col gap-1 text-sm">
        {headings.map((heading) => (
          <li key={heading.id} style={{ paddingLeft: `${((heading.level ?? 1) - 1) * 12}px` }}>
            <button
              type="button"
              onClick={() => scrollToElement(heading.id)}
              className="text-left text-zinc-600 hover:text-accent dark:text-zinc-400 dark:hover:text-accent"
            >
              {heading.content || "(untitled)"}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
