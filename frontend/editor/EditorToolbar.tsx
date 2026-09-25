"use client";

import { PanelRight } from "lucide-react";

import { useDocumentEditor } from "@/editor/EditorState";
import { RichTextToolbar } from "@/editor/RichTextToolbar";
import { setElementStyle } from "@/services/api";

/**
 * The toolbar row above the pages: the rich-text controls, and on narrow
 * screens the button that shows the Properties panel (wide screens always show
 * it beside the pages). Alignment outside tables is saved as the selected
 * element's own style, exactly like the Properties panel's.
 */
export function EditorToolbar({ onToggleProperties }: { onToggleProperties: () => void }) {
  const { editor, selection, change } = useDocumentEditor();
  const { selectedElementId, alignment } = selection;

  function align(value: string) {
    if (!selectedElementId) return;
    void change((documentId) => setElementStyle(documentId, selectedElementId, { property: "alignment", value })).catch(() => undefined);
  }

  return (
    <div className="mb-3 flex items-start gap-2 rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="min-w-0 flex-1">
        <RichTextToolbar editor={editor} alignment={alignment} onAlign={align} />
      </div>
      <button
        type="button"
        onClick={onToggleProperties}
        title="Properties"
        aria-label="Properties"
        className="flex h-8 shrink-0 items-center gap-1 rounded px-2 text-sm text-zinc-600 hover:bg-zinc-100 min-[1100px]:hidden dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        <PanelRight className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
