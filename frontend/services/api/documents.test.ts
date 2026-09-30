import { afterEach, describe, expect, it, vi } from "vitest";

import { setTrackedChanges } from "./documents";

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
});
