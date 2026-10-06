import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Document, ProposedChange } from "@/types/document";

import { ReviewPanel } from "./ReviewPanel";

const api = vi.hoisted(() => ({ acceptProposal: vi.fn(), rejectProposal: vi.fn(), acceptProposalsOfCategory: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const state = vi.hoisted(() => ({
  document: null as unknown as Document,
  change: vi.fn(async (action: (documentId: string) => Promise<unknown>) => action("doc-1")),
}));
vi.mock("@/editor/EditorState", () => ({ useDocumentEditor: () => ({ document: state.document, editor: null, change: state.change }) }));

function proposal(overrides: Partial<ProposedChange>): ProposedChange {
  return {
    id: "p",
    type: "delete_element",
    category: "content",
    elementId: "e1",
    afterElementId: null,
    elementType: null,
    property: null,
    before: "The second paragraph.",
    after: null,
    reason: "drop the second paragraph",
    source: "instruction",
    confidence: null,
    createdAt: "2026-10-07T00:00:00Z",
    problems: [],
    ...overrides,
  } as ProposedChange;
}

function documentWith(proposals: ProposedChange[]): Document {
  return { id: "doc-1", elements: [{ id: "e1", type: "paragraph", content: "The second paragraph." }], proposals } as unknown as Document;
}

const MIXED = [
  proposal({ id: "c1" }),
  proposal({ id: "s1", category: "structure", source: "health", type: "replace_content", before: "Deep", after: "Deep", reason: "Heading 3 → Heading 2" }),
  proposal({ id: "s2", category: "structure", source: "health", before: "", reason: "Delete an empty paragraph" }),
  proposal({ id: "t1", category: "translation", source: "translation", type: "replace_content", after: "Вторият абзац.", targetLanguage: "bg", reason: "Translated into Bulgarian" }),
];

afterEach(() => {
  api.acceptProposalsOfCategory.mockReset();
  api.acceptProposal.mockReset();
  state.change.mockClear();
});

describe("Review Changes (REV-002)", () => {
  it("says when nothing waits", () => {
    state.document = documentWith([]);
    render(<ReviewPanel />);
    expect(screen.getByText(/Nothing waits for review/)).toBeInTheDocument();
  });

  it("groups every kind of change by what it touches, with where it came from", () => {
    state.document = documentWith(MIXED);
    render(<ReviewPanel />);

    expect(screen.getByText("4 changes to review")).toBeInTheDocument();
    const content = screen.getByRole("region", { name: "Content changes" });
    expect(content).toHaveTextContent("AI instruction");
    expect(within(content).queryByRole("button", { name: /Accept all/ })).not.toBeInTheDocument(); // the words: one by one
    expect(screen.getByRole("region", { name: "Structure changes" })).toHaveTextContent("Health check");
    expect(screen.getByRole("region", { name: "Translation changes" })).toHaveTextContent("Вторият абзац.");

    fireEvent.click(screen.getByRole("button", { name: "Structure 2" }));
    expect(screen.queryByRole("region", { name: "Content changes" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Structure 2" })).toHaveAttribute("aria-pressed", "true");
  });

  it("accepts a whole category at once and says what was left waiting", async () => {
    state.document = documentWith(MIXED);
    api.acceptProposalsOfCategory.mockResolvedValueOnce({ document: documentWith([MIXED[0], MIXED[3]]), accepted: 1, skipped: 1 });
    render(<ReviewPanel />);

    fireEvent.click(within(screen.getByRole("region", { name: "Structure changes" })).getByRole("button", { name: "Accept all 2" }));

    await waitFor(() => expect(api.acceptProposalsOfCategory).toHaveBeenCalledWith("doc-1", "structure"));
    expect(await screen.findByRole("status")).toHaveTextContent("Accepted 1. 1 left waiting: they change the words or no longer fit");
  });

  it("accepts a change to the words on its own", async () => {
    state.document = documentWith(MIXED);
    api.acceptProposal.mockResolvedValueOnce(documentWith(MIXED.slice(1)));
    render(<ReviewPanel />);

    fireEvent.click(within(screen.getByRole("region", { name: "Content changes" })).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("doc-1", "c1"));
  });
});
