import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FormattingState } from "@/editor/useFormatting";

import { TemplatesPanel } from "./TemplatesPanel";

const api = vi.hoisted(() => ({
  extractReferenceStyle: vi.fn(),
  previewStyle: vi.fn(),
  createTemplate: vi.fn(),
}));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("@/editor/EditorState", () => ({
  useDocumentEditor: () => ({ document: { id: "doc-1", resolvedStyles: {}, metadata: { title: "Doc" } }, editor: null }),
}));

const blank = { fontFamily: null, fontSizePt: null, bold: null, italic: null, alignment: null, lineSpacing: null };

function reference() {
  return {
    suggestedName: "The look of reference",
    styleSystem: {
      page: { marginTopCm: 2, marginRightCm: 2, marginBottomCm: 2, marginLeftCm: 2, size: "A4", orientation: "portrait" },
      paragraph: { ...blank, fontFamily: "Georgia", fontSizePt: 12 },
      headings: { h1: { ...blank, fontSizePt: 20 } },
      header: { text: null },
      footer: { text: null, pageNumbers: null },
      structure: {
        tables: { border: "solid 0.5pt #000000", headerShading: "#dddddd", headerBold: true },
        lists: { bulletLevels: [{ format: "bullet", text: "■" }], numberedLevels: null },
        headingNumbering: null,
      },
    },
    notes: [],
    headingsFrom: "styles",
    headingCounts: { "1": 2 },
    counts: { paragraphs: 5, lists: 1, tables: 1, images: 0, captions: 0 },
    previewStyles: {},
    settings: {},
  };
}

function state(): FormattingState {
  return {
    templates: [],
    refreshTemplates: vi.fn(),
    templateId: "",
    setTemplateId: vi.fn(),
    isApplying: false,
    applyingFrom: null,
    progress: null,
    applyTemplate: vi.fn(),
  } as unknown as FormattingState;
}

describe("matching another document", () => {
  it("tries the reference's look on this document before anything is saved (FMT-003)", async () => {
    api.extractReferenceStyle.mockResolvedValueOnce(reference());
    api.previewStyle.mockResolvedValueOnce({
      before: { Paragraph: { "font-family": "Arial" } },
      after: { Paragraph: { "font-family": "Georgia" } },
      settingsBefore: {},
      settingsAfter: {},
      changes: ["Paragraph: font Arial → Georgia", "1 table: borders and header row as the look has them"],
      tables: 1,
      lists: 0,
    });
    render(<TemplatesPanel state={state()} />);
    fireEvent.change(screen.getByLabelText("Reference Word document"), { target: { files: [new File(["x"], "reference.docx")] } });

    const before = await screen.findByRole("region", { name: "Before and after" });
    expect(api.previewStyle).toHaveBeenCalledWith("doc-1", reference().styleSystem);
    expect(before).toHaveTextContent("Now");
    expect(before).toHaveTextContent("With this look");
    expect(before).toHaveTextContent("Paragraph: font Arial → Georgia");
    expect(screen.getByText(/tables ruled solid 0.5pt #000000, header rows shaded #dddddd, bold header rows, bullets ■/)).toBeInTheDocument();
    expect(api.createTemplate).not.toHaveBeenCalled(); // nothing saved by looking
  });

  it("still offers the look when the preview can't be had", async () => {
    api.extractReferenceStyle.mockResolvedValueOnce(reference());
    api.previewStyle.mockRejectedValueOnce(new Error("down"));
    render(<TemplatesPanel state={state()} />);
    fireEvent.change(screen.getByLabelText("Reference Word document"), { target: { files: [new File(["x"], "reference.docx")] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply to this document" })).toBeInTheDocument());
    expect(screen.queryByRole("region", { name: "Before and after" })).not.toBeInTheDocument();
  });
});
