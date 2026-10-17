import { afterEach, describe, expect, it, vi } from "vitest";

import { patchContent, proposeHealthFixes, REVISION_CONFLICT_EVENT, RevisionConflictError, setTrackedChanges } from "./documents";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the choice about a Word file's tracked changes", () => {
  it("is put to the document's own route (DOCX-022)", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "doc-1", revision: 3, trackedChanges: "accepted", elements: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    const document = await setTrackedChanges("doc-1", "accepted");

    const [path, init] = fetch.mock.calls[0];
    expect(path).toMatch(/\/documents\/doc-1\/tracked-changes$/);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ choice: "accepted" });
    expect(document.trackedChanges).toBe("accepted");
  });

  it("says that changes made here may go when rejecting them reads the document again (DOCX-022A)", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "doc-1", revision: 4, trackedChanges: "rejected", elements: [] }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetch);

    await setTrackedChanges("doc-1", "rejected", { discardEdits: true });

    expect(JSON.parse(fetch.mock.calls[0][1].body as string)).toEqual({ choice: "rejected", discardEdits: true });
  });
});

describe("a save of what changed (PERF-003)", () => {
  const patch = { changed: [], added: [], removed: ["b"], styles: [] };

  it("names the revision it was made from, and the next write builds on the answer's", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ revision: 8, changed: [], order: null, fields: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "doc-2", revision: 9, trackedChanges: "kept", elements: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);

    const saved = await patchContent("doc-2", 7, patch);
    await setTrackedChanges("doc-2", "kept");

    const [path, init] = fetch.mock.calls[0];
    expect(path).toMatch(/\/documents\/doc-2\/content$/);
    expect(init.method).toBe("PATCH");
    expect(new Headers(init.headers).get("If-Match")).toBe("7");
    expect(JSON.parse(init.body as string)).toEqual(patch);
    expect(saved.revision).toBe(8);
    expect(new Headers(fetch.mock.calls[1][1].headers).get("If-Match")).toBe("8");
  });

  it("leaves a 412 to the caller, who sends the whole document and lets that one say", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "revision_conflict", message: "Changed." }), { status: 412 })));
    const announced = vi.fn();
    window.addEventListener(REVISION_CONFLICT_EVENT, announced);
    try {
      await expect(patchContent("doc-3", 2, patch)).rejects.toBeInstanceOf(RevisionConflictError);
      expect(announced).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(REVISION_CONFLICT_EVENT, announced);
    }
  });
});

describe("Document Health fixes proposed (HLTH-002)", () => {
  it("are a write: the next write builds on the revision they made", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ document: { id: "doc-4", revision: 5, elements: [], proposals: [] }, proposalCount: 1 }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "doc-4", revision: 6, trackedChanges: "kept", elements: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetch);

    const answer = await proposeHealthFixes("doc-4", ["hierarchy"]);
    await setTrackedChanges("doc-4", "kept");

    const [path, init] = fetch.mock.calls[0];
    expect(path).toMatch(/\/documents\/doc-4\/health\/fixes$/);
    expect(JSON.parse(init.body as string)).toEqual({ checkIds: ["hierarchy"] });
    expect(answer.proposalCount).toBe(1);
    expect(new Headers(fetch.mock.calls[1][1].headers).get("If-Match")).toBe("5");
  });
});
