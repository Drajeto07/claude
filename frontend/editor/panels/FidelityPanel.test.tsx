import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FidelityItem, FidelityReport } from "@/types/document";

import { contentVerdict, FidelityPanel } from "./FidelityPanel";

type Shown = { importReport: FidelityReport | null; trackedChanges?: "kept" | "accepted" | null; sourcePackage?: object | null };
const state = vi.hoisted(() => ({
  document: { importReport: null } as Shown,
  notKept: [] as string[],
  change: vi.fn(async (action: (id: string) => Promise<unknown>) => action("doc-1")),
}));
const api = vi.hoisted(() => ({ setTrackedChanges: vi.fn(async () => ({})) }));
vi.mock("@/editor/EditorState", () => ({
  useDocumentEditor: () => ({ document: state.document, editor: null, notKept: state.notKept, change: state.change }),
}));
vi.mock("@/services/api", () => api);

function report(overrides: Partial<FidelityReport> = {}): FidelityReport {
  return {
    stage: "import",
    sourceType: "docx",
    createdAt: "2026-09-27T00:00:00Z",
    items: [],
    content: { method: "docx-text", verified: true, sourceWords: 750, resultWords: 750, missing: 0, added: 0, moved: 0, samples: [] },
    contentStatus: "verified",
    reviewCount: 0,
    contentLossCount: 0,
    ...overrides,
  };
}

const lostHeader: FidelityItem = {
  feature: "docx.header_footer.text",
  policy: "unsupported",
  reason: "Some header or footer text was left out.",
  elementIds: [],
  sourceState: "FIRST PAGE HEADER",
  newState: null,
  confidence: 1,
  count: 3,
  contentChanged: true,
};

describe("the content verdict", () => {
  it("says there are no content changes only when the words matched and nothing else was lost", () => {
    expect(contentVerdict(report())).toEqual({ tone: "good", text: "No content changes" });
    expect(contentVerdict(report({ items: [lostHeader], reviewCount: 1, contentLossCount: 1 })).text).toBe("Body text complete, some content left out");
    expect(contentVerdict(report({ contentStatus: "changed" })).text).toBe("Content differs from the source");
    expect(contentVerdict(report({ content: null, contentStatus: "unverified" })).tone).toBe("none");
    expect(contentVerdict(null).text).toBe("Content not verified");
  });
});

describe("the Проверка panel", () => {
  it("shows the verdict, the differences and each item", () => {
    state.document = {
      importReport: report({
        contentStatus: "changed",
        content: {
          method: "docx-text",
          verified: false,
          sourceWords: 10,
          resultWords: 9,
          missing: 1,
          added: 0,
          moved: 0,
          samples: [{ kind: "missing", source: "not", result: "", context: "Do" }],
        },
        items: [lostHeader],
        reviewCount: 1,
        contentLossCount: 1,
      }),
    };
    render(<FidelityPanel />);

    expect(screen.getByText("Content differs from the source")).toBeInTheDocument();
    expect(screen.getByText("Compared word by word with the Word file: 1 missing.")).toBeInTheDocument();
    expect(screen.getByText("not").tagName).toBe("DEL");
    expect(screen.getByText("1 to review")).toBeInTheDocument();
    expect(screen.getByText("Some header or footer text was left out.")).toBeInTheDocument();
    expect(screen.getByText("Was: FIRST PAGE HEADER")).toBeInTheDocument();
  });

  it("claims nothing for a document without a report", () => {
    state.document = { importReport: null };
    render(<FidelityPanel />);
    expect(screen.getByText("Content not verified")).toBeInTheDocument();
  });

  it("lists what the editor holds that the document can't keep", () => {
    state.document = { importReport: report() };
    state.notKept = ["Alignment inside lists, quotes and table cells isn't kept."];
    render(<FidelityPanel />);

    expect(screen.getByText("While editing")).toBeInTheDocument();
    expect(screen.getByText("Alignment inside lists, quotes and table cells isn't kept.")).toBeInTheDocument();
    state.notKept = [];
  });

  it("offers the choice about a Word file's tracked changes and makes it as a change (DOCX-022)", async () => {
    state.document = { importReport: report(), trackedChanges: "kept", sourcePackage: { assetId: "a", sha256: "0".repeat(64), size: 1 } };
    render(<FidelityPanel />);

    fireEvent.click(screen.getByRole("radio", { name: /Accept them all/ }));

    await waitFor(() => expect(api.setTrackedChanges).toHaveBeenCalledWith("doc-1", "accepted"));
    expect(state.change).toHaveBeenCalled();
  });

  it("offers no choice without the original file to keep them in", () => {
    state.document = { importReport: report(), trackedChanges: "kept", sourcePackage: null };
    render(<FidelityPanel />);

    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
});
