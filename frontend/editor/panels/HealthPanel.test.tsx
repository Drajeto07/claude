import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Document, HealthCheck, HealthReport, ProposedChange } from "@/types/document";

import { HealthPanel } from "./HealthPanel";

const api = vi.hoisted(() => ({ proposeHealthFixes: vi.fn(), acceptProposal: vi.fn(), rejectProposal: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const state = vi.hoisted(() => ({
  document: null as unknown as Document,
  report: null as unknown as HealthReport,
  change: vi.fn(async (action: (documentId: string) => Promise<unknown>) => action("doc-1")),
}));
vi.mock("@/editor/EditorState", () => ({ useDocumentEditor: () => ({ document: state.document, editor: null, change: state.change }) }));
vi.mock("@/services/queries", () => ({ useHealth: () => ({ data: state.report, isPending: false, isFetching: false, error: null }) }));

function check(overrides: Partial<HealthCheck>): HealthCheck {
  return { id: "x", title: "X", status: "pass", summary: "", issues: [], weight: 1, fixes: 0, ...overrides };
}

function fix(overrides: Partial<ProposedChange>): ProposedChange {
  return {
    id: "f",
    type: "replace_content",
    category: "structure",
    elementId: "h3",
    afterElementId: null,
    elementType: null,
    property: "level",
    before: "Deep heading",
    after: "Deep heading",
    reason: "Heading 3 → Heading 2: levels go down one at a time “Deep heading”",
    source: "health",
    confidence: null,
    createdAt: "2026-10-07T00:00:00Z",
    problems: [],
    ...overrides,
  } as ProposedChange;
}

function documentWith(proposals: ProposedChange[]): Document {
  return { id: "doc-1", revision: 3, elements: [{ id: "h3", type: "heading", content: "Deep heading" }], proposals } as unknown as Document;
}

afterEach(() => {
  api.proposeHealthFixes.mockReset();
  state.change.mockClear();
});

describe("Document Health fixes (HLTH-002)", () => {
  it("proposes a check's fixes for review rather than changing anything", async () => {
    state.document = documentWith([]);
    state.report = {
      score: 70,
      rating: "fair",
      checks: [
        check({ id: "hierarchy", title: "Structure", status: "warn", fixes: 1 }),
        check({ id: "empty_paragraphs", title: "Empty paragraphs", status: "warn", fixes: 2 }),
        check({ id: "alt_text", title: "Alt text", status: "fail", fixes: 0 }),
      ],
    };
    api.proposeHealthFixes.mockResolvedValueOnce({ document: documentWith([fix({})]), proposalCount: 1 });
    render(<HealthPanel />);

    expect(screen.getByRole("button", { name: "Propose all 3 fixes" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Propose fixes: Alt text" })).not.toBeInTheDocument(); // nothing to fix by rule
    fireEvent.click(screen.getByRole("button", { name: "Propose fixes: Structure" }));
    await waitFor(() => expect(api.proposeHealthFixes).toHaveBeenCalledWith("doc-1", ["hierarchy"]));
    expect(state.change).toHaveBeenCalledTimes(1);
  });

  it("shows a waiting fix with what it changes, to accept or reject", () => {
    state.document = documentWith([
      fix({}),
      fix({ id: "n", elementId: "l", type: "replace_content", category: "content", before: "1. First", after: "First", reason: "Remove the numbers typed at the start of 1 numbered item (the list numbers them)" }),
      fix({ id: "d", elementId: "e", type: "delete_element", before: "", after: null, reason: "Delete an empty paragraph (space paragraphs with spacing instead)" }),
    ]);
    state.report = { score: 90, rating: "good", checks: [check({})] };
    render(<HealthPanel />);

    const review = screen.getByRole("region", { name: "Changes to review" });
    expect(review).toHaveTextContent("Fixes from the checks wait for you here. Nothing changes until you accept.");
    expect(review).toHaveTextContent("Heading 3 → Heading 2");
    expect(review).toHaveTextContent("Now1. First");
    expect(review).toHaveTextContent("FixedFirst");
    expect(screen.getAllByRole("button", { name: "Accept" })).toHaveLength(3);
  });
});
