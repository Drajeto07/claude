import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { noticeForResult } from "@/editor/useFormatting";
import type { Document, ProposedChange } from "@/types/document";

import { ProposalsList } from "./ProposalsList";

const api = vi.hoisted(() => ({ acceptProposal: vi.fn(), rejectProposal: vi.fn() }));
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
    elementId: null,
    afterElementId: null,
    elementType: null,
    property: null,
    before: null,
    after: null,
    reason: "tidy the report",
    source: "instruction",
    confidence: null,
    createdAt: "2026-09-27T00:00:00Z",
    ...overrides,
  } as ProposedChange;
}

function documentWith(proposals: ProposedChange[]): Document {
  return {
    id: "doc-1",
    elements: [
      { id: "h", type: "heading", content: "Report" },
      { id: "p2", type: "paragraph", content: "The second paragraph, as edited since." },
    ],
    proposals,
  } as unknown as Document;
}

afterEach(() => {
  api.acceptProposal.mockReset();
  api.rejectProposal.mockReset();
  state.change.mockClear();
});

describe("changes to the text an instruction asked for", () => {
  it("shows each before anything happens: what goes (as it reads now), what comes, and where", () => {
    state.document = documentWith([
      proposal({ id: "d", type: "delete_element", elementId: "p2", before: "The second paragraph." }),
      proposal({ id: "i", type: "insert_element", afterElementId: "h", elementType: "paragraph", after: "An added paragraph." }),
      proposal({ id: "m", type: "move_element", elementId: "p2", afterElementId: null }),
    ]);

    render(<ProposalsList />);

    expect(screen.getByText("Changes to review (3)")).toBeInTheDocument();
    expect(screen.getByText("Nothing changes until you accept.", { exact: false })).toBeInTheDocument();
    const deleted = screen.getAllByText("The second paragraph, as edited since.")[0];
    expect(deleted).toHaveClass("line-through");
    expect(screen.getByText("Add a paragraph after “Report”")).toBeInTheDocument();
    expect(screen.getByText("An added paragraph.")).toBeInTheDocument();
    expect(screen.getByText("Move a block at the very start")).toBeInTheDocument();
    expect(screen.getAllByText("From: “tidy the report”")).toHaveLength(3);
  });

  it("accepts or rejects one at a time, through the document's change queue", async () => {
    state.document = documentWith([proposal({ id: "d", type: "delete_element", elementId: "p2" })]);
    api.acceptProposal.mockResolvedValue({});
    api.rejectProposal.mockResolvedValue({});
    render(<ProposalsList />);

    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(api.acceptProposal).toHaveBeenCalledWith("doc-1", "d"));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(api.rejectProposal).toHaveBeenCalledWith("doc-1", "d"));
    expect(state.change).toHaveBeenCalledTimes(2); // pending typing is saved first, then the result shown
  });

  it("says nothing when there is nothing to review", () => {
    state.document = documentWith([]);
    const { container } = render(<ProposalsList />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("the notice after formatting with instructions", () => {
  it("says what was applied and what waits for review", () => {
    expect(noticeForResult(true, false, 2, 0)).toEqual({ kind: "success", text: "Applied 2 changes from your instructions." });
    expect(noticeForResult(true, false, 1, 1)?.text).toBe(
      "Applied 1 change from your instructions. 1 change to the text waits for your review in Instructions -- nothing in the text changes until you accept.",
    );
    expect(noticeForResult(true, false, 0, 2)).toEqual({
      kind: "warning",
      text: "2 changes to the text wait for your review in Instructions -- nothing in the text changes until you accept.",
    });
    expect(noticeForResult(true, false, 0, 0)?.text).toContain("didn't produce any change");
  });
});
