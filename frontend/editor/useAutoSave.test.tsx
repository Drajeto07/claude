import { render, renderHook, screen, act } from "@testing-library/react";
import { Editor } from "@tiptap/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ContentPatch, Document } from "@/types/document";

import { EditorStatusBar } from "./EditorStatusBar";
import { editorExtensions } from "./extensions";
import { ApiError, NetworkError, RevisionConflictError } from "@/services/api";

import { NOT_KEPT, UnsupportedContentError } from "./tiptapToDocument";
import { useAutoSave } from "./useAutoSave";

const api = vi.hoisted(() => ({ updateContent: vi.fn(), patchContent: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  updateContent: api.updateContent,
  patchContent: api.patchContent,
}));

const editors: Editor[] = [];
afterEach(() => {
  while (editors.length) editors.pop()!.destroy();
  api.updateContent.mockReset();
  api.patchContent.mockReset();
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

  it("says why the server refused a save as too large, and doesn't retry it", async () => {
    vi.useFakeTimers();
    try {
      const { hook } = setup("<p>fine</p>");
      api.updateContent.mockRejectedValue(
        new ApiError(413, { code: "too_large", message: "A document can hold at most 1000 pictures." }, "Too large", "req-1"),
      );

      await act(async () => {
        await hook.result.current.flush().catch(() => undefined);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(hook.result.current.status).toBe("unsupported");
      expect(hook.result.current.problem).toBe("A document can hold at most 1000 pictures.");
      expect(api.updateContent).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("backs off a failing save instead of sending it again on every change it makes itself", async () => {
    vi.useFakeTimers();
    try {
      const { hook } = setup("<p>fine</p>");
      api.updateContent.mockRejectedValue(new ApiError(500, { code: "internal_error", message: "Something went wrong." }, "Error", null));

      await act(async () => {
        await hook.result.current.flush().catch(() => undefined);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      // At once, then 5 s and 15 s later: the new paragraph's id, set again on each try, schedules nothing.
      expect(api.updateContent).toHaveBeenCalledTimes(3);
      expect(hook.result.current.status).toBe("error");
    } finally {
      vi.useRealTimers();
    }
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

describe("autosave and the formatting the editor holds on blocks", () => {
  const SETTINGS = { pageWidthMm: 210, marginLeftCm: 2, marginRightCm: 2 };

  /** An editor whose document is kept as the server answers, as the editor shell does. */
  function saving(editorContent: string, resolvedStyles: Record<string, Record<string, string>> = {}) {
    const editor = new Editor({ extensions: editorExtensions, content: editorContent });
    editors.push(editor);
    const documentRef = { current: { id: "doc-1", elements: [], resolvedStyles, settings: SETTINGS } as unknown as Document };
    api.updateContent.mockImplementation((_id: string, elements: Document["elements"]) =>
      Promise.resolve({ ...documentRef.current, elements: elements.map((element) => ({ ...element, styleRef: element.styleRef ?? "Paragraph" })) }),
    );
    const hook = renderHook(() => useAutoSave(editor, documentRef, (saved) => (documentRef.current = saved)));
    return { editor, hook, documentRef };
  }

  it("saves an alignment set with a shortcut though no text changed", async () => {
    const { editor, hook } = saving("<p>Some text</p>");
    await act(async () => {
      await hook.result.current.flush();
    });
    editor.commands.setTextSelection(2);
    editor.commands.setTextAlign("center");

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(api.updateContent).toHaveBeenCalledTimes(2);
    const [, elements, styles] = api.updateContent.mock.calls[1];
    expect(styles).toEqual([{ elementId: elements[0].id, property: "alignment", value: "center", unit: null }]);
  });

  it("names formatting it can't keep, and still saves the rest", async () => {
    const { hook } = saving('<p><span style="color: hsl(0, 100%, 50%)">red words</span></p>');

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(api.updateContent).toHaveBeenCalledTimes(1);
    expect(hook.result.current.notKept).toEqual([NOT_KEPT.color]);
    render(
      <EditorStatusBar
        zoom={1}
        onZoomChange={() => undefined}
        onFitWidth={() => undefined}
        pageCount={1}
        onAddPage={() => undefined}
        saveStatus="saved"
        notKept={hook.result.current.notKept}
        onRetrySave={() => undefined}
      />,
    );
    expect(screen.getByText("1 formatting change not kept")).toHaveAttribute("title", expect.stringContaining(NOT_KEPT.color));
  });

  it("shows each block the look it was saved with", async () => {
    // Enter after a heading copies the heading's look onto the new paragraph; the saved document says what it is.
    const { editor, hook } = saving('<p style="font-size:20pt;font-weight:bold">Body text</p>', { Paragraph: { "font-size": "11pt" } });

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(editor.state.doc.child(0).attrs.style).toBe("font-size:11pt");
    expect(editor.can().undo()).toBe(false); // not an edit of its own
  });
});

describe("autosave sends what changed (PERF-003)", () => {
  /** An editor on a document the server knows (it has a revision), kept as the server answers. */
  function known(editorContent: string) {
    const editor = new Editor({ extensions: editorExtensions, content: editorContent });
    editors.push(editor);
    const documentRef = { current: { id: "doc-1", revision: 1, elements: [], resolvedStyles: {} } as unknown as Document };
    // The server stores what it is sent and says back what it now holds of it.
    api.patchContent.mockImplementation((_id: string, revision: number, patch: ContentPatch) =>
      Promise.resolve({
        revision: revision + 1,
        changed: [...patch.changed, ...patch.added.map((entry) => entry.element)].map((element) => ({ ...element, styleRef: "Paragraph" })),
        order: null,
        fields: {},
      }),
    );
    api.updateContent.mockImplementation((_id: string, elements: Document["elements"]) =>
      Promise.resolve({ ...documentRef.current, revision: documentRef.current.revision + 1, elements }),
    );
    const hook = renderHook(() => useAutoSave(editor, documentRef, (saved) => (documentRef.current = saved)));
    return { editor, hook, documentRef };
  }

  it("sends the paragraph typed in, not the document, and keeps what the server answers", async () => {
    const { editor, hook, documentRef } = known("<p>One</p><p>Two</p>");
    await act(async () => {
      await hook.result.current.flush();
    });
    expect(api.patchContent.mock.calls[0][2].added).toHaveLength(2);

    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    editor.commands.insertContent("!");
    await act(async () => {
      await hook.result.current.flush();
    });

    const [, revision, patch] = api.patchContent.mock.calls[1];
    expect(revision).toBe(2);
    expect(patch.changed.map((element: Document["elements"][number]) => element.content)).toEqual(["Two!"]);
    expect([patch.added, patch.removed]).toEqual([[], []]);
    expect(api.updateContent).not.toHaveBeenCalled();
    expect(documentRef.current.revision).toBe(3);
    expect(documentRef.current.elements.map((element) => [element.content, element.styleRef])).toEqual([
      ["One", "Paragraph"],
      ["Two!", "Paragraph"],
    ]);
    expect(hook.result.current.status).toBe("saved");
  });

  it("says 'not saved yet' from the first key to the end of the save, never 'saved' too early (B-026)", async () => {
    vi.useFakeTimers();
    try {
      const { editor, hook } = known("<p>One</p>");
      await act(async () => {
        await hook.result.current.flush();
      });
      expect(hook.result.current.status).toBe("saved");

      act(() => {
        editor.commands.setTextSelection(editor.state.doc.content.size - 1);
        editor.commands.insertContent(" more");
      });
      expect(hook.result.current.status).toBe("pending"); // typed, the save not started (debounce)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1300);
      });
      expect(hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("sends the whole document when the server doesn't take the patch", async () => {
    const { hook } = known("<p>One</p>");
    api.patchContent.mockRejectedValue(new ApiError(409, { code: "patch_mismatch", message: "The patch changes a block the document doesn't have." }, "Error", null));

    await act(async () => {
      await hook.result.current.flush();
    });

    expect(api.updateContent).toHaveBeenCalledTimes(1);
    expect(hook.result.current.status).toBe("saved");
  });

  it("tries a patch that failed otherwise again later, as any save", async () => {
    vi.useFakeTimers();
    try {
      const { hook } = known("<p>One</p>");
      api.patchContent.mockRejectedValueOnce(new ApiError(500, { code: "internal_error", message: "Something went wrong." }, "Error", null));

      await act(async () => {
        await hook.result.current.flush().catch(() => undefined);
      });
      expect(hook.result.current.status).toBe("error");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });

      expect(api.patchContent).toHaveBeenCalledTimes(2);
      expect(api.updateContent).not.toHaveBeenCalled();
      expect(hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the status after changes that end where the save is (B-038)", () => {
  /** An editor on a document the server knows; the server keeps what it is sent, and the test can read it. */
  function saved(editorContent: string) {
    const editor = new Editor({ extensions: editorExtensions, content: editorContent });
    editors.push(editor);
    const documentRef = { current: { id: "doc-1", revision: 1, elements: [], resolvedStyles: {} } as unknown as Document };
    api.patchContent.mockImplementation((_id: string, revision: number, patch: ContentPatch) =>
      Promise.resolve({
        revision: revision + 1,
        changed: [...patch.changed, ...patch.added.map((entry) => entry.element)].map((element) => ({ ...element, styleRef: "Paragraph" })),
        order: null,
        fields: {},
      }),
    );
    api.updateContent.mockImplementation((_id: string, elements: Document["elements"]) =>
      Promise.resolve({ ...documentRef.current, revision: documentRef.current.revision + 1, elements }),
    );
    const hook = renderHook(() => useAutoSave(editor, documentRef, (next) => (documentRef.current = next)));
    const saves = () => api.patchContent.mock.calls.length + api.updateContent.mock.calls.length;
    const stored = () => documentRef.current.elements.map((element) => element.content);
    const shown = () => editor.getJSON().content?.map((block) => (block.content ?? []).map((part) => (part as { text?: string }).text ?? "").join(""));
    const type = (text: string) =>
      act(() => {
        editor.commands.setTextSelection(editor.state.doc.content.size - 1);
        editor.commands.insertContent(text);
      });
    const pause = () =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(1300);
      });
    return { editor, hook, saves, stored, shown, type, pause };
  }

  async function settled(setup: ReturnType<typeof saved>) {
    await act(async () => {
      await setup.hook.result.current.flush();
    });
    expect(setup.hook.result.current.status).toBe("saved");
  }

  it("edit, save, undo, save: the undo is sent, and only then does it say saved", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      await doc.type(" more");
      await doc.pause();
      expect(doc.stored()).toEqual(["One more"]);
      const before = doc.saves();
      act(() => void doc.editor.commands.undo());
      expect(doc.hook.result.current.status).toBe("pending"); // a real change, not yet sent: never "saved"
      await doc.pause();
      expect(doc.saves()).toBe(before + 1);
      expect(doc.stored()).toEqual(["One"]);
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("undo and redo inside one pause: nothing to send, and it says saved -- not 'not saved yet' for good", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      await doc.type(" more");
      await doc.pause();
      const before = doc.saves();
      act(() => void doc.editor.commands.undo());
      act(() => void doc.editor.commands.redo());
      expect(doc.hook.result.current.status).toBe("pending");
      await doc.pause();
      expect(doc.saves()).toBe(before); // the editor holds exactly what is stored
      expect(doc.shown()).toEqual(doc.stored());
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("rapid undos and redos: whatever they end on is sent if it differs, and the status follows the server", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      await doc.type(" two");
      await doc.pause();
      await doc.type(" three");
      await doc.pause();
      expect(doc.stored()).toEqual(["One two three"]);
      const before = doc.saves();
      act(() => {
        doc.editor.commands.undo();
        doc.editor.commands.undo();
        doc.editor.commands.redo();
        doc.editor.commands.redo();
      });
      await doc.pause();
      expect(doc.saves()).toBe(before);
      expect(doc.hook.result.current.status).toBe("saved");
      act(() => {
        doc.editor.commands.undo();
        doc.editor.commands.undo();
        doc.editor.commands.redo();
      });
      await doc.pause();
      expect(doc.saves()).toBe(before + 1);
      expect(doc.stored()).toEqual(doc.shown());
      expect(doc.stored()).toEqual(["One two"]);
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed save, then a successful retry: 'saved' only once the server has it", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      api.patchContent.mockRejectedValueOnce(new ApiError(500, { code: "internal_error", message: "Something went wrong." }, "Error", null));
      await doc.type(" more");
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("error");
      expect(doc.stored()).toEqual(["One"]);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(doc.stored()).toEqual(["One more"]);
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed save undone back to what is stored: nothing is unsaved, so it says saved and stops retrying", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      api.patchContent.mockRejectedValueOnce(new ApiError(500, { code: "internal_error", message: "Something went wrong." }, "Error", null));
      await doc.type(" more");
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("error");
      const before = doc.saves();
      act(() => void doc.editor.commands.undo());
      await doc.pause();
      expect(doc.shown()).toEqual(doc.stored());
      expect(doc.hook.result.current.status).toBe("saved");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(70_000);
      });
      expect(doc.saves()).toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it("an undo with nothing to undo changes nothing and sends nothing", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      const before = doc.saves();
      act(() => void doc.editor.commands.undo());
      act(() => void doc.editor.commands.redo());
      await doc.pause();
      expect(doc.saves()).toBe(before);
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a change made while a save is on its way, then undone: the status ends saved, with the editor equal to the server", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      const real = api.patchContent.getMockImplementation()!;
      api.patchContent.mockImplementationOnce((...args: Parameters<typeof real>) => gate.then(() => real(...args)));
      await doc.type(" more");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1300); // the save starts and waits on the server
      });
      expect(doc.hook.result.current.status).toBe("saving");
      await doc.type("!");
      act(() => void doc.editor.commands.undo()); // the "!" goes again, while the save is still on its way
      await act(async () => {
        release();
        await vi.advanceTimersByTimeAsync(0);
      });
      await doc.pause();
      expect(doc.stored()).toEqual(doc.shown());
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("new typing while a save is on its way stays unsaved until its own save is answered", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      let release!: () => void;
      const gate = new Promise<void>((resolve) => (release = resolve));
      const real = api.patchContent.getMockImplementation()!;
      api.patchContent.mockImplementationOnce((...args: Parameters<typeof real>) => gate.then(() => real(...args)));
      await doc.type(" two");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1300);
      });
      expect(doc.hook.result.current.status).toBe("saving");
      await doc.type(" three"); // arrives while " two" is on its way
      await act(async () => {
        release();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(doc.stored()).toEqual(["One two"]);
      expect(doc.hook.result.current.status).toBe("pending"); // " three" isn't on the server: never "saved" here
      await doc.pause();
      expect(doc.stored()).toEqual(["One two three"]);
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed save while the change is still unsaved stays a failure", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      api.patchContent.mockRejectedValue(new ApiError(500, { code: "internal_error", message: "Something went wrong." }, "Error", null));
      await doc.type(" more");
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("error");
      await act(async () => {
        await doc.hook.result.current.flush().catch(() => undefined); // asked again: it fails again
      });
      expect(doc.hook.result.current.status).toBe("error");
      expect(doc.stored()).toEqual(["One"]);
      expect(doc.shown()).toEqual(["One more"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("offline with an unsaved change stays offline; once back to what is stored, there is nothing unsaved", async () => {
    vi.useFakeTimers();
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      api.patchContent.mockRejectedValue(new NetworkError());
      await doc.type(" more");
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("offline");
      await act(async () => {
        await doc.hook.result.current.flush().catch(() => undefined);
      });
      expect(doc.hook.result.current.status).toBe("offline"); // the change is still only here
      act(() => void doc.editor.commands.undo());
      await doc.pause();
      expect(doc.shown()).toEqual(doc.stored());
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      online.mockRestore();
      vi.useRealTimers();
    }
  });

  it("a real revision conflict stays a conflict, even when the change is undone back to what is stored", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      api.patchContent.mockRejectedValue(new RevisionConflictError());
      api.updateContent.mockRejectedValue(new RevisionConflictError());
      await doc.type(" more");
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("conflict");
      const before = doc.saves();
      act(() => void doc.editor.commands.undo());
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("conflict"); // never a false "saved": it was changed elsewhere
      expect(doc.saves()).toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it("formatting counts: bold alone is saved, and bold put back off inside one pause is nothing to send", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      const before = doc.saves();
      act(() => {
        doc.editor.commands.selectAll();
        doc.editor.commands.toggleBold();
      });
      expect(doc.hook.result.current.status).toBe("pending");
      await doc.pause();
      expect(doc.saves()).toBe(before + 1); // a look-only change is a change
      expect(doc.hook.result.current.status).toBe("saved");
      act(() => {
        doc.editor.commands.selectAll();
        doc.editor.commands.toggleBold();
        doc.editor.commands.selectAll();
        doc.editor.commands.toggleBold();
      });
      await doc.pause();
      expect(doc.saves()).toBe(before + 1);
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a save refused as too large stays refused while the content is still there, and is over once it is undone", async () => {
    vi.useFakeTimers();
    try {
      const doc = saved("<p>One</p>");
      await settled(doc);
      api.patchContent.mockRejectedValueOnce(new ApiError(413, { code: "too_large", message: "A document can hold at most 1000 pictures." }, "Too large", null));
      await doc.type(" more");
      await doc.pause();
      expect(doc.hook.result.current.status).toBe("unsupported");
      act(() => void doc.editor.commands.undo());
      await doc.pause();
      expect(doc.shown()).toEqual(doc.stored());
      expect(doc.hook.result.current.status).toBe("saved");
    } finally {
      vi.useRealTimers();
    }
  });
});
