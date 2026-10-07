import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BatchBar } from "./BatchBar";

/** Batch formatting (FEAT-001): one template over the ticked documents, followed until done. */

const api = vi.hoisted(() => ({ batchFormat: vi.fn(), getBatch: vi.fn(), batchExport: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("@/services/queries", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useTemplates: () => ({ data: [{ id: "academic-default", name: "Academic" }] }),
}));

function renderBar(selected: string[], onClear = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BatchBar selected={selected} onClear={onClear} />
    </QueryClientProvider>,
  );
  return onClear;
}

describe("the batch bar", () => {
  it("applies the chosen template to every ticked document and says how the batch went", async () => {
    api.batchFormat.mockResolvedValue({ id: "b1", jobs: [], total: 2, done: 0, failed: 0, conflicts: 0 });
    api.getBatch.mockResolvedValue({ id: "b1", jobs: [], total: 2, done: 2, failed: 0, conflicts: 1 });
    renderBar(["d1", "d2"]);

    const apply = screen.getByRole("button", { name: "Apply to 2 documents" });
    expect(apply).toBeDisabled(); // no template chosen yet
    fireEvent.change(screen.getByLabelText("Template"), { target: { value: "academic-default" } });
    fireEvent.click(apply);

    await waitFor(() => expect(api.batchFormat).toHaveBeenCalledWith(["d1", "d2"], "academic-default"));
    expect(await screen.findByRole("status")).toHaveTextContent("2 of 2 done; 1 with conflicts to resolve");
  });

  it("exports every ticked document into one ZIP and says what it holds (FEAT-002)", async () => {
    api.batchExport.mockResolvedValue({
      id: "job-9",
      result: {
        filename: "documents-pdf.zip",
        contentType: "application/zip",
        size: 10,
        parts: [
          { documentId: "d1", filename: "One.pdf", verified: true, missing: false },
          { documentId: "d2", filename: null, verified: false, missing: true },
        ],
      },
    });
    renderBar(["d1", "d2"]);

    fireEvent.change(screen.getByLabelText("Export format"), { target: { value: "pdf" } });
    fireEvent.click(screen.getByRole("button", { name: "Export as ZIP" }));

    const link = await screen.findByRole("link", { name: /documents-pdf\.zip/ });
    expect(api.batchExport).toHaveBeenCalledWith(["d1", "d2"], "pdf", expect.any(Function));
    expect(link.getAttribute("href")).toContain("/jobs/job-9/file");
    expect(screen.getByText(/1 file; each holding every word of its document; 1 deleted meanwhile, left out/)).toBeInTheDocument();
  });

  it("clears the selection", () => {
    const onClear = renderBar(["d1"]);
    fireEvent.click(screen.getByRole("button", { name: /Clear selection/ }));
    expect(onClear).toHaveBeenCalled();
  });
});
