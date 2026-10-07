import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Document, RepairReport } from "@/types/document";

import { RepairSection } from "./RepairSection";

/** Repair document (REV-004): what is broken by kind, each fix proposed for review, none applied here. */

const api = vi.hoisted(() => ({ proposeHealthFixes: vi.fn(async () => ({ document: { id: "doc-1" }, proposalCount: 1 })) }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
const state = vi.hoisted(() => ({
  report: null as unknown as RepairReport,
  change: vi.fn(async (action: (documentId: string) => Promise<unknown>) => action("doc-1")),
}));
vi.mock("@/editor/EditorState", () => ({ useDocumentEditor: () => ({ document: { id: "doc-1", revision: 2 } as unknown as Document, change: state.change }) }));
vi.mock("@/services/queries", () => ({ useRepair: () => ({ data: state.report }) }));

const REPORT: RepairReport = {
  fixes: 3,
  issues: [
    { kind: "tables", checkId: "broken_tables", title: "Table structure", status: "fail", summary: "1 table to repair.", elementIds: ["t1"], fixes: 1 },
    { kind: "links", checkId: "links", title: "Links", status: "warn", summary: "2 links go nowhere.", elementIds: ["p1", "p2"], fixes: 2 },
    { kind: "input", checkId: "import_content", title: "The file's text", status: "fail", summary: "3 words missing.", elementIds: [], fixes: 0 },
  ],
};

describe("repair document", () => {
  it("lists what is broken by kind and proposes a kind's fixes for review", async () => {
    state.report = REPORT;
    const onShow = vi.fn();
    render(<RepairSection onShow={onShow} />);

    expect(screen.getByText("Tables")).toBeInTheDocument();
    expect(screen.getByText("Malformed input")).toBeInTheDocument();
    expect(screen.getByText(/No fix can be worked out/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Propose repairs: Table structure" }));
    await waitFor(() => expect(api.proposeHealthFixes).toHaveBeenCalledWith("doc-1", ["broken_tables"]));

    fireEvent.click(screen.getByRole("button", { name: /Propose all 3 repairs/ }));
    await waitFor(() => expect(api.proposeHealthFixes).toHaveBeenLastCalledWith("doc-1", ["broken_tables", "links"]));
    fireEvent.click(screen.getByRole("button", { name: "Show 2" }));
    expect(onShow).toHaveBeenCalledWith("p2");
  });

  it("shows nothing when nothing is broken", () => {
    state.report = { issues: [], fixes: 0 };
    const { container } = render(<RepairSection onShow={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
