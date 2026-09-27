import { render, renderHook, screen, act } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Document } from "@/types/document";

import { EditorStatusBar } from "./EditorStatusBar";
import { editorExtensions } from "./extensions";
import { UnsupportedContentError } from "./tiptapToDocument";
import { useAutoSave } from "./useAutoSave";

const api = vi.hoisted(() => ({ updateContent: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), updateContent: api.updateContent }));

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
  api.updateContent.mockReset();
});

function setup(editorContent: string) {
  const editor = new Editor({ extensions: editorExtensions, content: editorContent });
  editors.push(editor);
  const documentRef = { current: { id: "doc-1", elements: [], resolvedStyles: {} } as unknown as Document };
  const hook = renderHook(() => useAutoSave(editor, documentRef, () => undefined));
  return { editor, hook };
}

/** Editor JSON holding a node no mapping knows, as a future extension or a bug could put there. */
function unknownContent(): ReturnType<Editor["getJSON"]> {
  return { type: "doc", attrs: {}, content: [{ type: "paragraph", attrs: {} }, { type: "mention", attrs: { id: "x" } }] };
}

describe("autosave and content the document can't store", () => {
  it("sends nothing and says why", async () => {
    const { editor, hook } = setup("<p>fine</p>");
    vi.spyOn(editor, "getJSON").mockReturnValue(unknownContent());

    let failure: unknown;
    await act(async () => {
      failure = await hook.result.current.flush().catch((error: unknown) => error);
    });

    expect(failure).toBeInstanceOf(UnsupportedContentError);
    expect(api.updateContent).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("unsupported");
    expect(hook.result.current.problem).toContain('"mention"');
  });

  it("saves again once the content is fine", async () => {
    const { editor, hook } = setup("<p>fine</p>");
    const spy = vi.spyOn(editor, "getJSON").mockReturnValue(unknownContent());
    await act(async () => {
      await hook.result.current.flush().catch(() => undefined);
    });
    spy.mockRestore();
    api.updateContent.mockResolvedValue({ id: "doc-1", elements: [], resolvedStyles: {} });

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(api.updateContent).toHaveBeenCalledTimes(1);
    expect(hook.result.current.status).toBe("saved");
    expect(hook.result.current.problem).toBeNull();
  });

  it("shows the problem in the status bar", () => {
    render(
      <EditorStatusBar
        zoom={1}
        onZoomChange={() => undefined}
        onFitWidth={() => undefined}
        pageCount={1}
        onAddPage={() => undefined}
        saveStatus="unsupported"
        saveProblem={'The document contains content of type "mention" that can\'t be saved yet.'}
        onRetrySave={() => undefined}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent('Not saved – The document contains content of type "mention"');
    expect(screen.getByRole("status")).toHaveTextContent("Undo the last change to continue.");
  });
});
