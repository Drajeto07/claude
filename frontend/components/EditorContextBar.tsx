import type { Editor } from "@tiptap/react";

import { Toolbar } from "@/components/Toolbar";

/**
 * The fixed top toolbar row (local Tiptap marks only -- font/size/bold/
 * align/lists). Per-element style overrides now live in the persistent
 * RightSidebar.tsx instead of inline here, matching the master-prompt
 * screenshot's layout (a fixed toolbar row + a separate right sidebar,
 * not a combined horizontal bar). Kept as its own component in case a
 * selection-dependent addition belongs here later, rather than importing
 * Toolbar directly into DocumentEditor.
 */
export function EditorContextBar({ editor }: { editor: Editor | null }) {
  return (
    <div className="mb-3 rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-800 dark:bg-zinc-900">
      <Toolbar editor={editor} />
    </div>
  );
}
