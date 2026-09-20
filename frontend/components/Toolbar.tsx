"use client";

import type { Editor } from "@tiptap/react";

import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";

const FONT_FAMILIES = ["Arial", "Times New Roman", "Calibri", "Georgia", "Courier New"];
const FONT_SIZES = ["10pt", "11pt", "12pt", "14pt", "16pt", "18pt", "24pt"];

function buttonClass(active: boolean): string {
  return `min-w-[2rem] rounded px-2 py-1 text-sm font-medium ${
    active
      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
      : "text-zinc-700 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-800"
  }`;
}

const selectClass =
  "rounded border border-zinc-300 bg-white px-1 py-1 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";

const Divider = () => <span className="mx-1 h-5 w-px bg-zinc-200 dark:bg-zinc-700" />;

/**
 * Direct Tiptap/ProseMirror mark toggles -- local to the editor only, not
 * routed through the backend's FormattingRule/resolvedStyles system.
 * Persisted per-element overrides are PropertiesPanel.tsx's job instead;
 * Toolbar edits stay ephemeral exactly like all other editing so far.
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
    <div className="mb-3 flex flex-wrap items-center gap-1 rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-800 dark:bg-zinc-900">
      <button type="button" title="Undo" onClick={() => editor.chain().focus().undo().run()} className={buttonClass(false)}>
        &#8630;
      </button>
      <button type="button" title="Redo" onClick={() => editor.chain().focus().redo().run()} className={buttonClass(false)}>
        &#8631;
      </button>
      <Divider />
      <button type="button" title="Bold" onClick={() => editor.chain().focus().toggleBold().run()} className={buttonClass(state.bold)}>
        <b>B</b>
      </button>
      <button type="button" title="Italic" onClick={() => editor.chain().focus().toggleItalic().run()} className={buttonClass(state.italic)}>
        <i>I</i>
      </button>
      <button
        type="button"
        title="Underline"
        onClick={() => editor.chain().focus().toggleUnderline().run()}
        className={buttonClass(state.underline)}
      >
        <u>U</u>
      </button>
      <button
        type="button"
        title="Strikethrough"
        onClick={() => editor.chain().focus().toggleStrike().run()}
        className={buttonClass(state.strike)}
      >
        <s>S</s>
      </button>
      <Divider />
      <select
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
        title="Align left"
        onClick={() => editor.chain().focus().setTextAlign("left").run()}
        className={buttonClass(state.alignLeft)}
      >
        &#8676;
      </button>
      <button
        type="button"
        title="Align center"
        onClick={() => editor.chain().focus().setTextAlign("center").run()}
        className={buttonClass(state.alignCenter)}
      >
        &#8596;
      </button>
      <button
        type="button"
        title="Align right"
        onClick={() => editor.chain().focus().setTextAlign("right").run()}
        className={buttonClass(state.alignRight)}
      >
        &#8677;
      </button>
      <button
        type="button"
        title="Justify"
        onClick={() => editor.chain().focus().setTextAlign("justify").run()}
        className={buttonClass(state.alignJustify)}
      >
        &#9776;
      </button>
      <Divider />
      <button
        type="button"
        title="Bullet list"
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        className={buttonClass(state.bulletList)}
      >
        &#8226;&#8212;
      </button>
      <button
        type="button"
        title="Numbered list"
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        className={buttonClass(state.orderedList)}
      >
        1.&#8212;
      </button>
    </div>
  );
}
