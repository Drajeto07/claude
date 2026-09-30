import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FidelityReport } from "@/types/document";

import { ExportResult } from "./ExportMenu";

function report(overrides: Partial<FidelityReport> = {}): FidelityReport {
  return {
    stage: "export",
    sourceType: "pdf",
    createdAt: "2026-09-27T00:00:00Z",
    items: [],
    content: { method: "pdf-export", verified: true, sourceWords: 12, resultWords: 14, missing: 0, added: 2, moved: 0, samples: [] },
    contentStatus: "verified",
    reviewCount: 0,
    contentLossCount: 0,
    ...overrides,
  };
}

describe("what the export's check found", () => {
  it("says every word is in the file only when the read-back proved it", () => {
    render(<ExportResult report={report()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Every word of the document is in the file.");
  });

  it("lists the words the file is missing", () => {
    const content = { method: "pdf-export", verified: false, sourceWords: 3, resultWords: 1, missing: 2, added: 0, moved: 0, samples: [{ kind: "missing" as const, source: "مرحبا بالعالم", result: "", context: "Hello" }] };
    render(<ExportResult report={report({ contentStatus: "changed", content })} />);
    expect(screen.getByRole("status")).toHaveTextContent("the file is missing words of the document");
    expect(screen.getByText("مرحبا بالعالم")).toBeInTheDocument();
  });

  it("names what was left out even when the text is complete", () => {
    const item = { feature: "export.docx.image_format", policy: "unsupported" as const, reason: "A picture Word can't read was left out.", elementIds: [], sourceState: null, newState: null, confidence: 1, count: 1, contentChanged: true };
    render(<ExportResult report={report({ items: [item], reviewCount: 1, contentLossCount: 1 })} />);
    expect(screen.getByRole("status")).toHaveTextContent("All the text is in the file, but some content was left out:");
    expect(screen.getByText(/A picture Word can't read/)).toBeInTheDocument();
  });

  it("claims nothing when the file couldn't be read back", () => {
    render(<ExportResult report={report({ content: null, contentStatus: "unverified" })} />);
    expect(screen.getByRole("status")).toHaveTextContent("The file couldn't be checked.");
  });
});
