import type { Editor } from "@tiptap/react";

import { Toolbar } from "@/components/Toolbar";

/**
 * The fixed top toolbar row. Per-element style overrides live in the
 * persistent RightSidebar.tsx, matching the master-prompt screenshot's layout
 * (a fixed toolbar row + a separate right sidebar). Kept as its own component
 * in case a selection-dependent addition belongs here later, rather than
 * importing Toolbar directly into DocumentEditor.
 */
export function EditorContextBar({
  editor,
  alignment,
  onAlign,
}: {
  editor: Editor | null;
  alignment?: string | null;
  onAlign?: (alignment: string) => void;
}) {
  return (
    <div className="mb-3 rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-800 dark:bg-zinc-900">
      <Toolbar editor={editor} alignment={alignment} onAlign={onAlign} />
    </div>
  );
}
