import { NodeSelection } from "@tiptap/pm/state";
import type { Editor } from "@tiptap/react";

/**
 * One selection model for Document Mode (E2, architecture §5): what is selected, so the toolbar, the properties
 * panel and the shortcuts all agree. Read from the editor's own state -- it is never stored twice.
 *   text  -- the cursor or a range in ordinary text (paragraphs, headings, lists, quotes...)
 *   table -- the cursor or a range inside a table (text tools plus table tools)
 *   image -- a picture selected as a whole
 *   none  -- no editor yet
 */
export type SelectionKind = "none" | "text" | "table" | "image";

export type BlockStyle = "body" | "h1" | "h2" | "h3" | "other";

export type EditorSelection = {
  kind: SelectionKind;
  /** A range of text is selected (not just a cursor). */
  hasRange: boolean;
  /** What the block the cursor is in is, for the text-style control. */
  block: BlockStyle;
};

export const NO_SELECTION: EditorSelection = { kind: "none", hasRange: false, block: "other" };

export function selectionOf(editor: Editor | null): EditorSelection {
  if (!editor || editor.isDestroyed) return NO_SELECTION;
  const { selection } = editor.state;
  if (selection instanceof NodeSelection && selection.node.type.name === "image") return { kind: "image", hasRange: false, block: "other" };
  const block: BlockStyle = editor.isActive("heading", { level: 1 })
    ? "h1"
    : editor.isActive("heading", { level: 2 })
      ? "h2"
      : editor.isActive("heading", { level: 3 })
        ? "h3"
        : editor.isActive("paragraph")
          ? "body"
          : "other";
  return { kind: editor.isActive("table") ? "table" : "text", hasRange: !selection.empty, block };
}
