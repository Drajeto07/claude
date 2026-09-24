"use client";

import type { Editor } from "@tiptap/react";
import type { ReactNode } from "react";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  Highlighter,
  Italic,
  List,
  ListChecks,
  ListOrdered,
  Redo2,
  RemoveFormatting,
  Strikethrough,
  Subscript as SubscriptIcon,
  Superscript as SuperscriptIcon,
  Underline as UnderlineIcon,
  Undo2,
} from "lucide-react";

import { useEditorForceUpdate } from "@/editor/useEditorForceUpdate";

const FONT_FAMILIES = ["Arial", "Times New Roman", "Calibri", "Cambria", "Georgia", "Verdana", "Courier New"];
const FONT_SIZES = ["8pt", "9pt", "10pt", "11pt", "12pt", "14pt", "16pt", "18pt", "20pt", "24pt", "28pt", "36pt"];
const ALIGNMENTS = [
  { value: "left", label: "Align left", Icon: AlignLeft },
  { value: "center", label: "Align center", Icon: AlignCenter },
  { value: "right", label: "Align right", Icon: AlignRight },
  { value: "justify", label: "Justify", Icon: AlignJustify },
] as const;

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

function ToggleButton({ label, active, onClick, children }: { label: string; active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} aria-pressed={active} title={label} onClick={onClick} className={buttonClass(active)}>
      {children}
    </button>
  );
}

/** A colour picker shown as a toolbar button: the icon, underlined in the current colour. */
function ColorButton({
  label,
  value,
  onPick,
  onClear,
  children,
}: {
  label: string;
  value: string | null;
  onPick: (color: string) => void;
  onClear: () => void;
  children: ReactNode;
}) {
  return (
    <span className="relative flex items-center">
      <label title={label} className={`${buttonClass(Boolean(value))} relative cursor-pointer flex-col gap-0.5`}>
        {children}
        <span className="h-1 w-4 rounded-sm" style={{ backgroundColor: value ?? "transparent", outline: value ? "none" : "1px solid #d4d4d8" }} />
        <input
          type="color"
          aria-label={label}
          value={value && /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000"}
          onChange={(event) => onPick(event.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
      </label>
      {value && (
        <button type="button" onClick={onClear} aria-label={`${label}: remove`} title={`Remove ${label.toLowerCase()}`} className="ml-0.5 text-xs text-zinc-400 hover:text-zinc-700">
          ×
        </button>
      )}
    </span>
  );
}

/**
 * Character formatting (bold, fonts, sizes, colours, highlight, super/subscript)
 * and lists are edited right here and saved with the text as marks. Paragraph
 * alignment is formatting of the whole element: outside tables it goes through
 * `onAlign`, which saves it as that element's own style (like the Properties
 * panel); inside a table it sets the cell's alignment, saved per column.
 */
export function Toolbar({
  editor,
  alignment,
  onAlign,
}: {
  editor: Editor | null;
  /** The selected element's current alignment (its resolved text-align). */
  alignment?: string | null;
  onAlign?: (alignment: string) => void;
}) {
  useEditorForceUpdate(editor);

  if (!editor) return null;

  const inTable = editor.isActive("table");
  const textStyle = editor.getAttributes("textStyle") as { color?: string | null; backgroundColor?: string | null };
  const state = {
    bold: editor.isActive("bold"),
    italic: editor.isActive("italic"),
    underline: editor.isActive("underline"),
    strike: editor.isActive("strike"),
    superscript: editor.isActive("superscript"),
    subscript: editor.isActive("subscript"),
    bulletList: editor.isActive("bulletList"),
    orderedList: editor.isActive("orderedList"),
    taskList: editor.isActive("taskList"),
  };
  const currentAlignment = inTable
    ? ALIGNMENTS.find(({ value }) => editor.isActive({ textAlign: value }))?.value ?? null
    : (alignment ?? null);

  function align(value: string) {
    if (inTable || !onAlign) editor!.chain().focus().setTextAlign(value).run();
    else onAlign(value);
  }

  return (
    <div className="flex flex-wrap items-center gap-1">
      <ToggleButton label="Undo" active={false} onClick={() => editor.chain().focus().undo().run()}>
        <Undo2 className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Redo" active={false} onClick={() => editor.chain().focus().redo().run()}>
        <Redo2 className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <Divider />
      <ToggleButton label="Bold" active={state.bold} onClick={() => editor.chain().focus().toggleBold().run()}>
        <Bold className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Italic" active={state.italic} onClick={() => editor.chain().focus().toggleItalic().run()}>
        <Italic className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Underline" active={state.underline} onClick={() => editor.chain().focus().toggleUnderline().run()}>
        <UnderlineIcon className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Strikethrough" active={state.strike} onClick={() => editor.chain().focus().toggleStrike().run()}>
        <Strikethrough className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Superscript" active={state.superscript} onClick={() => editor.chain().focus().toggleSuperscript().run()}>
        <SuperscriptIcon className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Subscript" active={state.subscript} onClick={() => editor.chain().focus().toggleSubscript().run()}>
        <SubscriptIcon className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
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
      <ColorButton
        label="Text colour"
        value={textStyle.color ?? null}
        onPick={(color) => editor.chain().focus().setColor(color).run()}
        onClear={() => editor.chain().focus().unsetColor().run()}
      >
        <Baseline className="h-4 w-4" aria-hidden="true" />
      </ColorButton>
      <ColorButton
        label="Highlight"
        value={textStyle.backgroundColor ?? null}
        onPick={(color) => editor.chain().focus().setBackgroundColor(color).run()}
        onClear={() => editor.chain().focus().unsetBackgroundColor().run()}
      >
        <Highlighter className="h-4 w-4" aria-hidden="true" />
      </ColorButton>
      <ToggleButton label="Clear formatting" active={false} onClick={() => editor.chain().focus().unsetAllMarks().run()}>
        <RemoveFormatting className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <Divider />
      {ALIGNMENTS.map(({ value, label, Icon }) => (
        <ToggleButton key={value} label={label} active={currentAlignment === value} onClick={() => align(value)}>
          <Icon className="h-4 w-4" aria-hidden="true" />
        </ToggleButton>
      ))}
      <Divider />
      <ToggleButton label="Bullet list" active={state.bulletList} onClick={() => editor.chain().focus().toggleBulletList().run()}>
        <List className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Numbered list" active={state.orderedList} onClick={() => editor.chain().focus().toggleOrderedList().run()}>
        <ListOrdered className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
      <ToggleButton label="Checklist" active={state.taskList} onClick={() => editor.chain().focus().toggleTaskList().run()}>
        <ListChecks className="h-4 w-4" aria-hidden="true" />
      </ToggleButton>
    </div>
  );
}
