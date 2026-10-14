import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";
import type { Document, Element } from "@/types/document";

import { DocumentFlow } from "./DocumentFlow";

const nav = vi.hoisted(() => ({ push: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({ useRouter: () => nav, useSearchParams: () => nav.params }));

const api = vi.hoisted(() => ({
  importText: vi.fn(),
  importFile: vi.fn(),
  formatDocument: vi.fn(),
  renameDocument: vi.fn(),
  updateContent: vi.fn(),
  setTrackedChanges: vi.fn(),
  createTemplate: vi.fn(),
  extractReferenceStyle: vi.fn(),
}));
vi.mock("@/services/api", () => api);

const ai = vi.hoisted(() => ({ configured: false }));
vi.mock("@/services/queries", () => ({
  useTemplates: () => ({
    isPending: false,
    data: [
      { id: "modern", name: "Modern", description: "Clean", isDefault: true, previewStyles: {} },
      { id: "professional-cv", name: "Professional CV", description: "For CVs", isDefault: false, previewStyles: {} },
    ],
  }),
  useBilling: () => ({ data: { plan: { entitlements: { maxDocumentSizeMb: 10 } } } }),
  useAiAvailability: () => ({ data: ai.configured }),
}));
vi.mock("@/components/TemplatePreviewSample", () => ({ TemplatePreviewSample: () => null }));

function block(id: string, type: Element["type"], level: number | null, order: number, confidence: number | null = 0.9): Element {
  return { id, type, content: id, level, order, confidence } as Element;
}

const imported = {
  id: "doc-1",
  metadata: { title: "Notes" },
  revision: 1,
  trackedChanges: null,
  sourcePackage: null,
  elements: [block("Intro", "heading", 1, 0), block("first words", "paragraph", null, 1, 0.4), block("Plan", "heading", 1, 2), block("more words", "paragraph", null, 3)],
} as unknown as Document;

beforeEach(() => {
  nav.params = new URLSearchParams();
  ai.configured = false;
  api.importText.mockResolvedValue(imported);
  api.updateContent.mockImplementation(async (_id: string, elements: Element[]) => ({ ...imported, revision: 2, elements }));
  api.renameDocument.mockImplementation(async (_id: string, title: string) => ({ ...imported, metadata: { title } }));
  api.formatDocument.mockResolvedValue(imported);
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderFlow(locale: "en" | "bg" = "en") {
  return render(
    <I18nProvider locale={locale}>
      <DocumentFlow />
    </I18nProvider>,
  );
}

async function pasteAndAnalyse() {
  fireEvent.change(screen.getByLabelText("Your text"), { target: { value: "Intro\nfirst words\nPlan\nmore words" } });
  fireEvent.click(screen.getByRole("button", { name: "Analyse the structure" }));
  await screen.findByRole("heading", { level: 1, name: "Check the structure" });
}

describe("the document flow (S2-020): content, structure, look, editor", () => {
  it("starts with the content; nothing is sent until there is some", () => {
    renderFlow();
    expect(screen.getByRole("heading", { level: 1, name: "Add your content" })).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyse the structure" })).toBeDisabled();
    expect(api.importText).not.toHaveBeenCalled();
  });

  it("pasted text is imported, then its structure is shown with what to check", async () => {
    renderFlow();
    await pasteAndAnalyse();
    expect(api.importText).toHaveBeenCalledWith("Intro\nfirst words\nPlan\nmore words", undefined, expect.any(Function));
    expect(screen.getByText("2 headings · 2 paragraphs · 0 other blocks")).toBeInTheDocument();
    expect(screen.getByText("1 blocks to check: SmartDoc wasn’t sure about them.")).toBeInTheDocument();
    expect(screen.getByLabelText("Project name")).toHaveValue("Notes");
  });

  it("confirming changes saves the kinds, the new order and the name -- once, before the look", async () => {
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.change(screen.getByLabelText("What “first words” is"), { target: { value: "h2" } });
    fireEvent.click(screen.getByRole("button", { name: "Move “Plan” up" }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Field notes" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));

    await screen.findByRole("heading", { level: 1, name: "Choose the look" });
    expect(api.renameDocument).toHaveBeenCalledWith("doc-1", "Field notes");
    expect(api.updateContent).toHaveBeenCalledOnce();
    const [, saved] = api.updateContent.mock.calls[0] as [string, Element[]];
    expect(saved.map((element) => element.id)).toEqual(["Plan", "more words", "Intro", "first words"]);
    expect(saved.find((element) => element.id === "first words")).toMatchObject({ type: "heading", level: 2 });
  });

  it("confirming without a change saves nothing", async () => {
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
    await screen.findByRole("heading", { level: 1, name: "Choose the look" });
    expect(api.updateContent).not.toHaveBeenCalled();
    expect(api.renameDocument).not.toHaveBeenCalled();
  });

  it("the look: the template the link named is chosen; applying formats, then opens the editor", async () => {
    nav.params = new URLSearchParams("template=professional-cv");
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
    await screen.findByRole("heading", { level: 1, name: "Choose the look" });

    expect(screen.getByRole("button", { name: /Professional CV/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Apply and open the editor" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/documents/doc-1"));
    expect(api.formatDocument).toHaveBeenCalledWith("doc-1", expect.objectContaining({ templateId: "professional-cv", instructionsText: undefined }));
  });

  it("'Open without formatting' goes straight to the editor", async () => {
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open without formatting" }));
    expect(nav.push).toHaveBeenCalledWith("/documents/doc-1");
    expect(api.formatDocument).not.toHaveBeenCalled();
  });

  it("instructions are called AI only when a model is configured", async () => {
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
    await screen.findByRole("heading", { level: 1, name: "Choose the look" });
    expect(screen.getByText(/No AI model is connected on this server/)).toBeInTheDocument();
    expect(screen.queryByText(/An AI model reads your instructions/)).toBeNull();
  });

  it("with a model configured, it says so", async () => {
    ai.configured = true;
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
    expect(await screen.findByText("An AI model reads your instructions and proposes the formatting.")).toBeInTheDocument();
  });

  it("when the import fails: says why and stays on the content", async () => {
    api.importText.mockRejectedValue(new Error("The text is too long for your plan."));
    renderFlow();
    fireEvent.change(screen.getByLabelText("Your text"), { target: { value: "words" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyse the structure" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The text is too long for your plan.");
    expect(screen.getByRole("heading", { level: 1, name: "Add your content" })).toBeInTheDocument();
  });

  it("in Bulgarian", () => {
    renderFlow("bg");
    expect(screen.getByRole("heading", { level: 1, name: "Добавете съдържанието" })).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("button", { name: "Анализирай структурата" })).toBeDisabled();
  });
});
