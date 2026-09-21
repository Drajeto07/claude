import type { Editor } from "@tiptap/react";

import { PropertiesPanel } from "@/components/PropertiesPanel";
import { Toolbar } from "@/components/Toolbar";
import type { Document } from "@/types/document";

/**
 * The audit's "contextual quick-actions toolbar" pattern: local Tiptap marks
 * (Toolbar, always available -- there's almost always an active caret) plus,
 * only when something is selected, the backend-persisted per-element style
 * override group (PropertiesPanel). These stay two separate mechanisms on
 * purpose (local/ephemeral vs. persisted/priority-winning) -- merged here
 * only in presentation, with a divider + label so that distinction stays
 * legible rather than reading as one undifferentiated control set.
 */
export function EditorContextBar({
  editor,
  document,
  selectedElementId,
  onUpdated,
}: {
  editor: Editor | null;
  document: Document;
  selectedElementId: string | null;
  onUpdated: (updated: Document) => void;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-start gap-4 rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-800 dark:bg-zinc-900">
      <Toolbar editor={editor} />
      {selectedElementId && (
        <>
          <span className="mt-1 h-8 w-px shrink-0 bg-zinc-200 dark:bg-zinc-700" aria-hidden="true" />
          <div>
            <p className="mb-1.5 text-[10px] font-semibold tracking-wide text-zinc-400 uppercase dark:text-zinc-500">
              Element style
            </p>
            <PropertiesPanel document={document} selectedElementId={selectedElementId} onUpdated={onUpdated} />
          </div>
        </>
      )}
    </div>
  );
}
