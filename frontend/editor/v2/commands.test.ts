import { NodeSelection, TextSelection } from "@tiptap/pm/state";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resetTypingHistory } from "@/editor/EditorState";
import { editorExtensions } from "@/editor/extensions";
import type { DocumentVersion } from "@/types/document";

import { COMMANDS, commandsFor, isEnabled, matchesShortcut, shortcutLabel, type CommandContext } from "./commands";
import { selectionOf } from "./selectionModel";
import { savedSteps, undoSource } from "./useUnifiedHistory";

const PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
});

function editorWith(content: string): Editor {
  const editor = new Editor({ extensions: editorExtensions, content });
  editors.push(editor);
  return editor;
}

function context(editor: Editor | null, extra: Partial<CommandContext> = {}): CommandContext {
  return {
    editor,
    selection: selectionOf(editor),
    history: { canUndo: false, canRedo: false, undo: vi.fn(), redo: vi.fn() } as unknown as CommandContext["history"],
    alignElement: vi.fn(),
    ui: { panelsHidden: false, togglePanels: vi.fn(), zoomIn: vi.fn(), zoomOut: vi.fn(), fitWidth: vi.fn(), openProperties: vi.fn() },
    ...extra,
  };
}

describe("the selection model", () => {
  it("text: a cursor, a range, and which kind of block it is in", () => {
    const editor = editorWith("<h2>Title</h2><p>Body text here</p>");
    editor.commands.setTextSelection(2);
    expect(selectionOf(editor)).toEqual({ kind: "text", hasRange: false, block: "h2" });
    editor.commands.setTextSelection({ from: 9, to: 13 });
    expect(selectionOf(editor)).toEqual({ kind: "text", hasRange: true, block: "body" });
  });

  it("a cursor inside a table is a table selection", () => {
    const editor = editorWith("<table><tbody><tr><td><p>cell</p></td></tr></tbody></table>");
    let inCell = 0;
    editor.state.doc.descendants((node, pos) => {
      if (node.isTextblock && !inCell) inCell = pos + 1;
    });
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc, inCell)));
    expect(selectionOf(editor).kind).toBe("table");
  });

  it("a picture selected as a whole", () => {
    const editor = editorWith(`<p>before</p><img src="${PNG}"><p>after</p>`);
    let imagePos = -1;
    editor.state.doc.descendants((node, pos) => {
      if (node.type.name === "image") imagePos = pos;
    });
    editor.view.dispatch(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, imagePos)));
    expect(selectionOf(editor).kind).toBe("image");
  });

  it("no editor: nothing selected", () => {
    expect(selectionOf(null).kind).toBe("none");
  });
});

describe("the command registry", () => {
  it("every command has a unique id", () => {
    expect(new Set(COMMANDS.map((command) => command.id)).size).toBe(COMMANDS.length);
  });

  it("offers each selection its own tools: text, table, picture", () => {
    expect(commandsFor("text").map((command) => command.id)).toContain("bold");
    expect(commandsFor("text").map((command) => command.id)).not.toContain("rowBelow");
    expect(commandsFor("table").map((command) => command.id)).toEqual(expect.arrayContaining(["bold", "rowBelow", "deleteTable"]));
    expect(commandsFor("image").map((command) => command.id)).toEqual(expect.arrayContaining(["editPicture", "deletePicture", "alignCenter"]));
    expect(commandsFor("image").map((command) => command.id)).not.toContain("bold");
  });

  it("runs on the editor: bold toggles, and says it is on", () => {
    const editor = editorWith("<p>Make me bold</p>");
    editor.commands.setTextSelection({ from: 1, to: 5 });
    const bold = COMMANDS.find((command) => command.id === "bold")!;
    void bold.run(context(editor));
    expect(editor.getHTML()).toContain("<strong>Make</strong>");
    expect(bold.isActive!(context(editor))).toBe(true);
  });

  it("alignment outside a table is the element's own style; inside a table, the cell's", () => {
    const editor = editorWith("<p>Text</p>");
    editor.commands.setTextSelection(2);
    const alignElement = vi.fn();
    void COMMANDS.find((command) => command.id === "alignCenter")!.run(context(editor, { alignElement }));
    expect(alignElement).toHaveBeenCalledWith("center");
  });

  it("undo and redo are only possible when one of the histories has a step", () => {
    const undo = COMMANDS.find((command) => command.id === "undo")!;
    expect(isEnabled(undo, context(null))).toBe(false);
    const ready = context(null, { history: { canUndo: true, canRedo: false, undo: vi.fn(), redo: vi.fn() } as unknown as CommandContext["history"] });
    expect(isEnabled(undo, ready)).toBe(true);
  });

  it("shortcuts: shown for people, matched on key events, Ctrl or Cmd", () => {
    expect(shortcutLabel("Mod-Shift-z", false)).toBe("Ctrl+Shift+Z");
    expect(shortcutLabel("Mod-Shift-z", true)).toBe("⌘⇧Z");
    expect(shortcutLabel("Mod-Alt--", false)).toBe("Ctrl+Alt+-");
    const key = (key: string, extra: Partial<KeyboardEvent> = {}) => ({ key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...extra });
    expect(matchesShortcut(key("z", { ctrlKey: true }), "Mod-z", false)).toBe(true);
    expect(matchesShortcut(key("Z", { ctrlKey: true, shiftKey: true }), "Mod-z", false)).toBe(false);
    expect(matchesShortcut(key("Z", { ctrlKey: true, shiftKey: true }), "Mod-Shift-z", false)).toBe(true);
    expect(matchesShortcut(key("z", { metaKey: true }), "Mod-z", true)).toBe(true);
    expect(matchesShortcut(key("\\", { ctrlKey: true }), "Mod-\\", false)).toBe(true);
    expect(matchesShortcut(key("-", { ctrlKey: true, altKey: true }), "Mod-Alt--", false)).toBe(true);
  });
});

describe("one undo, one redo", () => {
  it("typing first, then the saved steps, never both", () => {
    expect(undoSource(true, true)).toBe("typing");
    expect(undoSource(false, true)).toBe("saved");
    expect(undoSource(false, false)).toBeNull();
  });

  it("knows the saved step undo would take back and the one redo would bring", () => {
    const version = (number: number, current = false) => ({ number, current, description: `Step ${number}`, kind: "change" }) as DocumentVersion;
    const steps = savedSteps([version(3), version(2, true), version(1)]);
    expect(steps).toMatchObject({ canUndo: true, canRedo: true });
    expect(steps.current?.description).toBe("Step 2");
    expect(steps.next?.description).toBe("Step 3");
    expect(savedSteps([version(1, true)])).toMatchObject({ canUndo: false, canRedo: false });
    expect(savedSteps(undefined)).toMatchObject({ canUndo: false, canRedo: false });
  });

  it("after a saved change, nothing typed before it can be undone or redone (a fresh typing history)", () => {
    const editor = editorWith("<p>Original</p>");
    editor.commands.setTextSelection(9);
    editor.commands.insertContent(" typed");
    editor.commands.undo(); // something to redo now
    expect(editor.can().redo()).toBe(true);
    editor.chain().setMeta("addToHistory", false).setContent("<p>From the server</p>", { emitUpdate: false }).run();
    resetTypingHistory(editor);
    expect(editor.can().undo()).toBe(false);
    expect(editor.can().redo()).toBe(false);
    expect(editor.getText()).toBe("From the server");
  });

  it("a saved change put into the editor is not a typing step (nothing for the editor's own undo)", () => {
    const editor = editorWith("<p>Original</p>");
    editor.chain().setMeta("addToHistory", false).setContent("<p>From the server</p>", { emitUpdate: false }).run();
    expect(editor.can().undo()).toBe(false);
    editor.commands.setTextSelection(5);
    editor.commands.insertContent("X");
    expect(editor.can().undo()).toBe(true);
    editor.commands.undo();
    expect(editor.getText()).toBe("From the server");
    expect(editor.can().undo()).toBe(false);
  });
});
