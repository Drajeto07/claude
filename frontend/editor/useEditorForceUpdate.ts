import { useEffect, useState } from "react";
import type { Editor } from "@tiptap/react";

/**
 * Forces a re-render on every editor transaction/selection change, so a
 * component can read fresh editor.isActive()/editor.state.selection values
 * directly in its render body. (Tiptap 3's useEditorState hook looked like
 * the more idiomatic choice, but its snapshot never resolved past `null`
 * here even once `editor` itself was ready -- see Toolbar.tsx's original
 * fix. This is the shared version of that workaround.)
 */
export function useEditorForceUpdate(editor: Editor | null): void {
  const [, forceRender] = useState(0);
  useEffect(() => {
    if (!editor) return;
    const rerender = () => forceRender((n) => n + 1);
    editor.on("transaction", rerender);
    editor.on("selectionUpdate", rerender);
    return () => {
      editor.off("transaction", rerender);
      editor.off("selectionUpdate", rerender);
    };
  }, [editor]);
}
