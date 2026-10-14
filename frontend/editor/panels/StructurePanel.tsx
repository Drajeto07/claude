"use client";

import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { visibleText } from "@/editor/hiddenText";
import { useI18n } from "@/i18n/I18nProvider";
import { format } from "@/i18n/locales";
import type { Element } from "@/types/document";

function scrollToElement(id: string) {
  document.querySelector(`[data-element-id="${id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

type OutlineNode = { heading: Element; children: OutlineNode[] };

// Headings only carry a flat `level` (1-6), not a parent pointer -- this
// rebuilds the nesting a stack-based walk, the same technique
// documentToTiptap.ts's buildNestedListItems uses for list items.
function buildOutlineTree(headings: Element[]): OutlineNode[] {
  const roots: OutlineNode[] = [];
  const stack: OutlineNode[] = [];
  for (const heading of headings) {
    const node: OutlineNode = { heading, children: [] };
    const level = heading.level ?? 1;
    while (stack.length > 0 && (stack[stack.length - 1].heading.level ?? 1) >= level) stack.pop();
    (stack.length === 0 ? roots : stack[stack.length - 1].children).push(node);
    stack.push(node);
  }
  return roots;
}

function OutlineItem({ node }: { node: OutlineNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const t = useI18n().m.edPanels.structure;
  const hasChildren = node.children.length > 0;

  return (
    <li>
      <div className="flex items-center gap-1">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? t.expand : t.collapse}
            className="flex h-4 w-4 shrink-0 items-center justify-center text-muted hover:text-foreground"
          >
            {collapsed ? <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />}
          </button>
        ) : (
          <span className="w-4 shrink-0" aria-hidden="true" />
        )}
        <button
          type="button"
          onClick={() => scrollToElement(node.heading.id)}
          className="truncate text-left text-muted hover:text-accent"
        >
          {visibleText(node.heading).trim() || t.untitled}
        </button>
      </div>
      {hasChildren && !collapsed && (
        <ul className="ml-5 flex flex-col gap-1 border-l border-line pl-2">
          {node.children.map((child) => (
            <OutlineItem key={child.heading.id} node={child} />
          ))}
        </ul>
      )}
    </li>
  );
}

function AiAnalysisCard({ elements }: { elements: Element[] }) {
  const t = useI18n().m.edPanels.structure;
  const scored = elements.filter((el) => el.confidence !== null);
  if (scored.length === 0) return null;

  const lowConfidence = scored.filter((el) => (el.confidence ?? 0) < 0.6);
  const allConfident = lowConfidence.length === 0;

  return (
    <div
      className={`mt-4 rounded-lg border p-3 ${
        allConfident
          ? "border-success/30 bg-success/10"
          : "border-warning/40 bg-warning-soft"
      }`}
    >
      <p
        className={`flex items-center gap-1.5 text-sm font-medium ${
          allConfident ? "text-success" : "text-warning"
        }`}
      >
        {allConfident ? <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /> : <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />}
        {t.aiTitle}
      </p>
      <p className={`mt-1 text-xs ${allConfident ? "text-success" : "text-warning"}`}>
        {allConfident
          ? format(t.allConfident, { count: scored.length })
          : format(t.someLow, { low: lowConfidence.length, count: scored.length })}
      </p>
    </div>
  );
}

export function StructurePanel({ elements }: { elements: Element[] }) {
  const t = useI18n().m.edPanels.structure;
  const headings = elements.filter((el) => el.type === "heading").sort((a, b) => a.order - b.order);
  const tree = buildOutlineTree(headings);

  return (
    <div>
      {tree.length === 0 ? (
        <p className="text-sm text-muted">{t.noHeadings}</p>
      ) : (
        <nav>
          <ul className="flex flex-col gap-1.5 text-sm">
            {tree.map((node) => (
              <OutlineItem key={node.heading.id} node={node} />
            ))}
          </ul>
        </nav>
      )}
      <AiAnalysisCard elements={elements} />
    </div>
  );
}
