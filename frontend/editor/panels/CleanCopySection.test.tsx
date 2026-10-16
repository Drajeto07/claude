import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Document } from "@/types/document";

import { CleanCopySection } from "./CleanCopySection";

/** Clean copy (REV-005): nothing ticked to begin with; only what is ticked is taken out. */

const api = vi.hoisted(() => ({ createCleanCopy: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
const state = vi.hoisted(() => ({ document: { id: "doc-1", trackedChanges: null } as unknown as Document, flush: vi.fn(async () => undefined) }));
vi.mock("@/editor/EditorState", () => ({ useDocumentEditor: () => ({ document: state.document, flush: state.flush }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

afterEach(() => api.createCleanCopy.mockReset());

describe("a clean copy", () => {
  it("is made with only what is ticked, after what is typed is saved, and says what it took out", async () => {
    api.createCleanCopy.mockResolvedValue({
      document: { id: "doc-2", metadata: { title: "Report (clean copy)" } },
      summary: { commentsRemoved: 2, trackedChangesAccepted: false, hiddenRunsRemoved: 0, metadataRemoved: ["author"], formattingRemoved: 0, originalFileLeftOut: true },
    });
    render(<CleanCopySection />);
    const create = screen.getByRole("button", { name: "Create clean copy" });
    expect(create).toBeDisabled(); // nothing chosen

    fireEvent.click(screen.getByLabelText("Remove comments"));
    fireEvent.click(screen.getByLabelText(/Remove the file's metadata/));
    fireEvent.click(create);

    await waitFor(() =>
      expect(api.createCleanCopy).toHaveBeenCalledWith("doc-1", {
        removeComments: true,
        acceptTrackedChanges: false,
        removeHiddenText: false,
        removeMetadata: true,
        normaliseFormatting: false,
      }),
    );
    expect(state.flush).toHaveBeenCalled();
    expect(await screen.findByText(/2 comments removed; metadata removed \(author\)/)).toBeInTheDocument();
    expect(screen.getByText(/no original Word file behind it/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Report \(clean copy\)/ })).toHaveAttribute("href", "/documents/doc-2");
  });

  it("says a document keeping tracked changes can only have them accepted", () => {
    state.document = { id: "doc-1", trackedChanges: "kept" } as unknown as Document;
    render(<CleanCopySection />);
    expect(screen.getByText(/can only have them accepted/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Accept tracked changes"));
    expect(screen.queryByText(/can only have them accepted/)).toBeNull();
    state.document = { id: "doc-1", trackedChanges: null } as unknown as Document;
  });
});
