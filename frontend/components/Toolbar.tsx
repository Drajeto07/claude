"use client";

import type { Editor } from "@tiptap/react";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Italic,
  List,
  ListOrdered,
  Redo2,
  Strikethrough,
  Underline as UnderlineIcon,
  Undo2,
} from "lucide-react";

import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";

const FONT_FAMILIES = ["Arial", "Times New Roman", "Calibri", "Georgia", "Courier New"];
const FONT_SIZES = ["10pt", "11pt", "12pt", "14pt", "16pt", "18pt", "24pt"];

function buttonClass(active: boolean): string {
  return `flex h-8 min-w-[2rem] items-center justify-center rounded px-2 text-sm font-medium transition-colors ${
    active
      ? "bg-accent/10 text-accent"
      : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
  }`;
}

const selectClass =
  "h-8 rounded border border-zinc-300 bg-white px-1 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";

const Divider = () => <span className="mx-1 h-6 w-px bg-zinc-200 dark:bg-zinc-700" aria-hidden="true" />;

/**
 * Direct Tiptap/ProseMirror mark toggles -- local to the editor only, not
 * routed through the backend's FormattingRule/resolvedStyles system.
 * Persisted per-element overrides are PropertiesPanel.tsx's job instead;
 * Toolbar edits stay ephemeral exactly like all other editing so far.
 * Rendered inside EditorContextBar's own bordered container -- no box of
 * its own here.
 */
export function Toolbar({ editor }: { editor: Editor | null }) {
  useEditorForceUpdate(editor);

  if (!editor) return null;

  const state = {
    bold: editor.isActive("bold"),
    italic: editor.isActive("italic"),
    underline: editor.isActive("underline"),
    strike: editor.isActive("strike"),
    bulletList: editor.isActive("bulletList"),
    orderedList: editor.isActive("orderedList"),
    alignLeft: editor.isActive({ textAlign: "left" }),
    alignCenter: editor.isActive({ textAlign: "center" }),
    alignRight: editor.isActive({ textAlign: "right" }),
    alignJustify: editor.isActive({ textAlign: "justify" }),
  };

  return (
    <div className="flex flex-wrap items-center gap-1">
      <button
        type="button"
        aria-label="Undo"
        title="Undo"
        onClick={() => editor.chain().focus().undo().run()}
        className={buttonClass(false)}
      >
        <Undo2 className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Redo"
        title="Redo"
        onClick={() => editor.chain().focus().redo().run()}
        className={buttonClass(false)}
      >
        <Redo2 className="h-4 w-4" aria-hidden="true" />
      </button>
      <Divider />
      <button
        type="button"
        aria-label="Bold"
        aria-pressed={state.bold}
        title="Bold"
        onClick={() => editor.chain().focus().toggleBold().run()}
        className={buttonClass(state.bold)}
      >
        <Bold className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Italic"
        aria-pressed={state.italic}
        title="Italic"
        onClick={() => editor.chain().focus().toggleItalic().run()}
        className={buttonClass(state.italic)}
      >
        <Italic className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Underline"
        aria-pressed={state.underline}
        title="Underline"
        onClick={() => editor.chain().focus().toggleUnderline().run()}
        className={buttonClass(state.underline)}
      >
        <UnderlineIcon className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Strikethrough"
        aria-pressed={state.strike}
        title="Strikethrough"
        onClick={() => editor.chain().focus().toggleStrike().run()}
        className={buttonClass(state.strike)}
      >
        <Strikethrough className="h-4 w-4" aria-hidden="true" />
      </button>
      <Divider />
      <select
        aria-label="Font family"
        title="Font family"
        defaultValue=""
        onChange={(e) => {
          if (e.target.value) editor.chain().focus().setFontFamily(e.target.value).run();
          e.target.value = "";
        }}
        className={selectClass}
      >
        <option value="" disabled>
          Font
        </option>
        {FONT_FAMILIES.map((font) => (
          <option key={font} value={font}>
            {font}
          </option>
        ))}
      </select>
      <select
        aria-label="Font size"
        title="Font size"
        defaultValue=""
        onChange={(e) => {
          if (e.target.value) editor.chain().focus().setFontSize(e.target.value).run();
          e.target.value = "";
        }}
        className={selectClass}
      >
        <option value="" disabled>
          Size
        </option>
        {FONT_SIZES.map((size) => (
          <option key={size} value={size}>
            {size}
          </option>
        ))}
      </select>
      <Divider />
      <button
        type="button"
        aria-label="Align left"
        aria-pressed={state.alignLeft}
        title="Align left"
        onClick={() => editor.chain().focus().setTextAlign("left").run()}
        className={buttonClass(state.alignLeft)}
      >
        <AlignLeft className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Align center"
        aria-pressed={state.alignCenter}
        title="Align center"
        onClick={() => editor.chain().focus().setTextAlign("center").run()}
        className={buttonClass(state.alignCenter)}
      >
        <AlignCenter className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Align right"
        aria-pressed={state.alignRight}
        title="Align right"
        onClick={() => editor.chain().focus().setTextAlign("right").run()}
        className={buttonClass(state.alignRight)}
      >
        <AlignRight className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Justify"
        aria-pressed={state.alignJustify}
        title="Justify"
        onClick={() => editor.chain().focus().setTextAlign("justify").run()}
        className={buttonClass(state.alignJustify)}
      >
        <AlignJustify className="h-4 w-4" aria-hidden="true" />
      </button>
      <Divider />
      <button
        type="button"
        aria-label="Bullet list"
        aria-pressed={state.bulletList}
        title="Bullet list"
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        className={buttonClass(state.bulletList)}
      >
        <List className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label="Numbered list"
        aria-pressed={state.orderedList}
        title="Numbered list"
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        className={buttonClass(state.orderedList)}
      >
        <ListOrdered className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
