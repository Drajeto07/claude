import type { Editor } from "@tiptap/react";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Bold,
  Columns3,
  Image as ImageIcon,
  Italic,
  List,
  ListChecks,
  ListOrdered,
  PanelLeftClose,
  Redo2,
  RemoveFormatting,
  Rows3,
  Scan,
  Strikethrough,
  Subscript,
  Superscript,
  Table2,
  Trash2,
  Underline,
  Undo2,
  ZoomIn,
  ZoomOut,
  type LucideIcon,
} from "lucide-react";

import type { EditorSelection, SelectionKind } from "./selectionModel";
import type { UnifiedHistory } from "./useUnifiedHistory";

/**
 * The command registry (E2, architecture §6): every action of the 2.0 editor once -- its label (from the
 * dictionaries, by id), icon, shortcut, where it applies, whether it is on or possible, and what it does. The
 * contextual toolbar, the shortcuts and the tooltips read this list, so a command behaves the same wherever it
 * is used, and it is tested once.
 */

export type CommandContext = {
  editor: Editor | null;
  selection: EditorSelection;
  history: UnifiedHistory;
  /** An element's alignment, saved as its own style (outside tables), like the properties panel. */
  alignElement: (value: string) => void;
  ui: {
    panelsHidden: boolean;
    togglePanels: () => void;
    zoomIn: () => void;
    zoomOut: () => void;
    fitWidth: () => void;
    openProperties: () => void;
  };
};

export type CommandId =
  | "undo"
  | "redo"
  | "bold"
  | "italic"
  | "underline"
  | "strike"
  | "superscript"
  | "subscript"
  | "clearFormatting"
  | "alignLeft"
  | "alignCenter"
  | "alignRight"
  | "alignJustify"
  | "bulletList"
  | "orderedList"
  | "taskList"
  | "rowAbove"
  | "rowBelow"
  | "columnLeft"
  | "columnRight"
  | "deleteRow"
  | "deleteColumn"
  | "headerRow"
  | "deleteTable"
  | "editPicture"
  | "deletePicture"
  | "togglePanels"
  | "zoomIn"
  | "zoomOut"
  | "fitWidth";

export type CommandGroup = "history" | "marks" | "align" | "lists" | "table" | "picture" | "view";

export type Command = {
  id: CommandId;
  group: CommandGroup;
  icon: LucideIcon;
  /** Shortcut, in ProseMirror's notation (Mod = Ctrl, or Cmd on a Mac). */
  shortcut?: string;
  /** Other keys for the same command (Mod-y for redo). */
  extraShortcuts?: string[];
  /** Handled here, not by the text engine's own keymap (which already knows Mod-b, Mod-i...). */
  globalShortcut?: boolean;
  /** Where it applies; absent: everywhere. */
  kinds?: SelectionKind[];
  isActive?: (context: CommandContext) => boolean;
  isEnabled?: (context: CommandContext) => boolean;
  run: (context: CommandContext) => unknown;
};

const TEXT: SelectionKind[] = ["text", "table"];
const chain = (context: CommandContext) => context.editor!.chain().focus();
const active = (name: string, attributes?: Record<string, unknown>) => (context: CommandContext) => Boolean(context.editor?.isActive(name, attributes));

/** Alignment: in a table, the cell's (saved per column by the engine); elsewhere, the element's own style. */
function align(value: string): Command["run"] {
  return (context) => {
    if (context.selection.kind === "table") chain(context).setTextAlign(value).run();
    else context.alignElement(value);
  };
}

export const COMMANDS: Command[] = [
  { id: "undo", group: "history", icon: Undo2, shortcut: "Mod-z", globalShortcut: true, isEnabled: (c) => c.history.canUndo, run: (c) => c.history.undo() },
  { id: "redo", group: "history", icon: Redo2, shortcut: "Mod-Shift-z", extraShortcuts: ["Mod-y"], globalShortcut: true, isEnabled: (c) => c.history.canRedo, run: (c) => c.history.redo() },

  { id: "bold", group: "marks", icon: Bold, shortcut: "Mod-b", kinds: TEXT, isActive: active("bold"), run: (c) => chain(c).toggleBold().run() },
  { id: "italic", group: "marks", icon: Italic, shortcut: "Mod-i", kinds: TEXT, isActive: active("italic"), run: (c) => chain(c).toggleItalic().run() },
  { id: "underline", group: "marks", icon: Underline, shortcut: "Mod-u", kinds: TEXT, isActive: active("underline"), run: (c) => chain(c).toggleUnderline().run() },
  { id: "strike", group: "marks", icon: Strikethrough, kinds: TEXT, isActive: active("strike"), run: (c) => chain(c).toggleStrike().run() },
  { id: "superscript", group: "marks", icon: Superscript, kinds: TEXT, isActive: active("superscript"), run: (c) => chain(c).toggleSuperscript().run() },
  { id: "subscript", group: "marks", icon: Subscript, kinds: TEXT, isActive: active("subscript"), run: (c) => chain(c).toggleSubscript().run() },
  { id: "clearFormatting", group: "marks", icon: RemoveFormatting, kinds: TEXT, run: (c) => chain(c).unsetAllMarks().run() },

  { id: "alignLeft", group: "align", icon: AlignLeft, kinds: ["text", "table", "image"], run: align("left") },
  { id: "alignCenter", group: "align", icon: AlignCenter, kinds: ["text", "table", "image"], run: align("center") },
  { id: "alignRight", group: "align", icon: AlignRight, kinds: ["text", "table", "image"], run: align("right") },
  { id: "alignJustify", group: "align", icon: AlignJustify, kinds: TEXT, run: align("justify") },

  { id: "bulletList", group: "lists", icon: List, kinds: TEXT, isActive: active("bulletList"), run: (c) => chain(c).toggleBulletList().run() },
  { id: "orderedList", group: "lists", icon: ListOrdered, kinds: TEXT, isActive: active("orderedList"), run: (c) => chain(c).toggleOrderedList().run() },
  { id: "taskList", group: "lists", icon: ListChecks, kinds: TEXT, isActive: active("taskList"), run: (c) => chain(c).toggleTaskList().run() },

  { id: "rowAbove", group: "table", icon: Rows3, kinds: ["table"], run: (c) => chain(c).addRowBefore().run() },
  { id: "rowBelow", group: "table", icon: Rows3, kinds: ["table"], run: (c) => chain(c).addRowAfter().run() },
  { id: "columnLeft", group: "table", icon: Columns3, kinds: ["table"], run: (c) => chain(c).addColumnBefore().run() },
  { id: "columnRight", group: "table", icon: Columns3, kinds: ["table"], run: (c) => chain(c).addColumnAfter().run() },
  { id: "headerRow", group: "table", icon: Table2, kinds: ["table"], run: (c) => chain(c).toggleHeaderRow().run() },
  { id: "deleteRow", group: "table", icon: Trash2, kinds: ["table"], run: (c) => chain(c).deleteRow().run() },
  { id: "deleteColumn", group: "table", icon: Trash2, kinds: ["table"], run: (c) => chain(c).deleteColumn().run() },
  { id: "deleteTable", group: "table", icon: Trash2, kinds: ["table"], run: (c) => chain(c).deleteTable().run() },

  { id: "editPicture", group: "picture", icon: ImageIcon, kinds: ["image"], run: (c) => c.ui.openProperties() },
  { id: "deletePicture", group: "picture", icon: Trash2, kinds: ["image"], run: (c) => chain(c).deleteSelection().run() },

  { id: "togglePanels", group: "view", icon: PanelLeftClose, shortcut: "Mod-\\", globalShortcut: true, isActive: (c) => c.ui.panelsHidden, run: (c) => c.ui.togglePanels() },
  { id: "zoomOut", group: "view", icon: ZoomOut, shortcut: "Mod-Alt--", globalShortcut: true, run: (c) => c.ui.zoomOut() },
  { id: "zoomIn", group: "view", icon: ZoomIn, shortcut: "Mod-Alt-=", globalShortcut: true, run: (c) => c.ui.zoomIn() },
  { id: "fitWidth", group: "view", icon: Scan, shortcut: "Mod-Alt-0", globalShortcut: true, run: (c) => c.ui.fitWidth() },
];

export const COMMAND_BY_ID = Object.fromEntries(COMMANDS.map((command) => [command.id, command])) as Record<CommandId, Command>;

/** The commands for a selection, in registry order. */
export function commandsFor(kind: SelectionKind, group?: CommandGroup): Command[] {
  return COMMANDS.filter((command) => (!command.kinds || command.kinds.includes(kind)) && (!group || command.group === group));
}

export const isEnabled = (command: Command, context: CommandContext) => (!command.kinds || command.kinds.includes(context.selection.kind)) && (command.isEnabled?.(context) ?? true);

/** A shortcut for people: "Ctrl+Shift+Z", "⌘⇧Z" on a Mac. */
export function shortcutLabel(shortcut: string, mac: boolean): string {
  const keys = shortcut.split("-").map((key, index, all) => (key === "" && index === all.length - 1 ? "-" : key)).filter(Boolean);
  const names: Record<string, [string, string]> = { Mod: ["Ctrl", "⌘"], Shift: ["Shift", "⇧"], Alt: ["Alt", "⌥"] };
  const parts = keys.map((key) => names[key]?.[mac ? 1 : 0] ?? (key.length === 1 ? key.toUpperCase() : key));
  return mac ? parts.join("") : parts.join("+");
}

/** Whether a key event is this shortcut (Mod = Ctrl, or Cmd on a Mac). */
export function matchesShortcut(event: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey">, shortcut: string, mac: boolean): boolean {
  const parts = shortcut.split("-");
  const key = parts.at(-1) === "" ? "-" : parts.at(-1)!;
  const mods = new Set(parts.slice(0, parts.at(-1) === "" ? -2 : -1));
  const mod = mac ? event.metaKey : event.ctrlKey;
  if (mods.has("Mod") !== mod || mods.has("Shift") !== event.shiftKey || mods.has("Alt") !== event.altKey) return false;
  return event.key.toLowerCase() === key.toLowerCase() || (key === "=" && event.key === "+");
}
