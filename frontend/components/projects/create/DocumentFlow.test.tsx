import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
  getDocument: vi.fn(),
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
      { id: "academic-default", name: "Академичен", description: "Курсова работа", category: "academic", builtin: true, isDefault: false, previewStyles: {} },
      { id: "modern-report", name: "Модерен доклад", description: "Бизнес доклад", category: "business", builtin: true, isDefault: false, previewStyles: {} },
      { id: "professional-cv", name: "Професионален (CV)", description: "CV / мотивационно писмо", category: "professional", builtin: true, isDefault: false, previewStyles: {} },
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

const report = {
  ...imported,
  metadata: { title: "Годишен отчет 2026" },
  elements: [block("Годишен отчет 2026", "heading", 1, 0), block("Приходите растат.", "paragraph", null, 1), block("t", "table", null, 2)],
} as unknown as Document;

beforeEach(() => {
  nav.params = new URLSearchParams();
  ai.configured = false;
  window.sessionStorage.clear();
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
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider locale={locale}>
        <DocumentFlow />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

async function pasteAndAnalyse(text = "Intro\nfirst words\nPlan\nmore words") {
  fireEvent.change(screen.getByLabelText("Your text"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Analyse the structure" }));
  await screen.findByRole("heading", { level: 1, name: "Check the structure" });
}

async function toLook() {
  await pasteAndAnalyse();
  fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
  await screen.findByRole("heading", { level: 1, name: "Choose the look" });
}

describe("the document flow (S2-020): content, structure, look, editor", () => {
  it("starts with the content; nothing is sent until there is some", () => {
    renderFlow();
    expect(screen.getByRole("heading", { level: 1, name: "Add your content" })).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyse the structure" })).toBeDisabled();
    expect(api.importText).not.toHaveBeenCalled();
  });

  it("pasted text is imported, its structure shown, and the step goes into the address", async () => {
    renderFlow();
    await pasteAndAnalyse();
    expect(api.importText).toHaveBeenCalledWith("Intro\nfirst words\nPlan\nmore words", undefined, expect.any(Function));
    expect(nav.push).toHaveBeenCalledWith("/new?step=structure&doc=doc-1", { scroll: true });
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
    await toLook();
    expect(api.updateContent).not.toHaveBeenCalled();
    expect(api.renameDocument).not.toHaveBeenCalled();
  });

  it("the outline can show only headings, or only what to check", async () => {
    renderFlow();
    await pasteAndAnalyse();
    const outline = screen.getByRole("region", { name: "Blocks of the document" });
    fireEvent.click(screen.getByRole("radio", { name: "Headings" }));
    expect(within(outline).getAllByRole("listitem")).toHaveLength(2);
    fireEvent.click(screen.getByRole("radio", { name: "To check (1)" }));
    expect(within(outline).getAllByRole("listitem")).toHaveLength(1);
    expect(within(outline).getByText("first words")).toBeInTheDocument();
  });

  it("back to the content: the text is still there, and continuing doesn't import it again", async () => {
    renderFlow();
    await pasteAndAnalyse();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Your text")).toHaveValue("Intro\nfirst words\nPlan\nmore words");
    expect(screen.getByText("Already analysed as “Notes”.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Continue with it/ }));
    await screen.findByRole("heading", { level: 1, name: "Check the structure" });
    expect(api.importText).toHaveBeenCalledOnce();
  });

  it("the look: the template the link named is chosen and shown as selected; applying formats, then opens the editor", async () => {
    nav.params = new URLSearchParams("template=professional-cv");
    renderFlow();
    await toLook();
    const chosen = screen.getByRole("button", { name: /Professional \(CV\)/ }); // the server's Bulgarian name, shown in English (S2-028)
    expect(chosen).toHaveAttribute("aria-pressed", "true");
    expect(chosen).toHaveTextContent("Selected");
    fireEvent.click(screen.getByRole("button", { name: "Apply and open the editor" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/documents/doc-1"));
    expect(api.formatDocument).toHaveBeenCalledWith("doc-1", expect.objectContaining({ templateId: "professional-cv", instructionsText: undefined }));
  });

  it("a report is suggested its look, with the reasons, and says the rules suggested it -- not AI", async () => {
    api.importText.mockResolvedValue(report);
    renderFlow();
    await pasteAndAnalyse("Годишен отчет 2026");
    fireEvent.click(screen.getByRole("button", { name: "Confirm the structure" }));
    const suggestion = await screen.findByRole("region", { name: "Suggested for this document" });
    expect(suggestion).toHaveTextContent("Modern report");
    expect(suggestion).toHaveTextContent("it mentions “отчет”, “приходите” and it has a table");
    expect(suggestion).toHaveTextContent("not by AI");
    // With no default and no link choice, the suggestion is preselected -- and can be changed.
    expect(screen.getByRole("button", { name: /^Modern report/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("'Open without formatting' goes straight to the editor", async () => {
    renderFlow();
    await toLook();
    fireEvent.click(screen.getByRole("button", { name: "Open without formatting" }));
    expect(nav.push).toHaveBeenCalledWith("/documents/doc-1");
    expect(api.formatDocument).not.toHaveBeenCalled();
  });

  it("instructions are called AI only when a model is configured", async () => {
    renderFlow();
    await toLook();
    expect(screen.getByText(/No AI model is connected on this server/)).toBeInTheDocument();
    expect(screen.queryByText(/An AI model reads your instructions/)).toBeNull();
  });

  it("with a model configured, it says so", async () => {
    ai.configured = true;
    renderFlow();
    await toLook();
    expect(screen.getByText("An AI model reads your instructions and proposes the formatting.")).toBeInTheDocument();
  });

  it("after a reload on a later step, the draft is read again by its id", async () => {
    nav.params = new URLSearchParams("step=structure&doc=doc-1");
    api.getDocument.mockResolvedValue(imported);
    renderFlow();
    await screen.findByRole("heading", { level: 1, name: "Check the structure" });
    expect(await screen.findByLabelText("Project name")).toHaveValue("Notes");
    expect(api.getDocument).toHaveBeenCalledWith("doc-1");
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
