import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Document, ProposedChange } from "@/types/document";

import { ProposalsList } from "./ProposalsList";
import { TRANSLATION_LABEL, TranslatePanel } from "./TranslatePanel";

const api = vi.hoisted(() => ({
  getDocumentLanguage: vi.fn(async () => ({ set: null, detected: "en", script: "Latn", direction: "ltr", confidence: 0.95, name: "English" })),
  setDocumentLanguage: vi.fn(async () => ({})),
  setGlossary: vi.fn(async () => ({})),
  translateBlocks: vi.fn(),
  translateDocument: vi.fn(async () => "doc-2"),
  acceptProposal: vi.fn(),
  rejectProposal: vi.fn(),
}));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/editor/translationTarget", () => ({ translationTarget: () => ({ elementIds: ["p1"], selection: { start: 0, end: 4 } }) }));

const state = vi.hoisted(() => ({
  document: null as unknown as Document,
  change: vi.fn(async (action: (documentId: string) => Promise<unknown>) => action("doc-1")),
  flush: vi.fn(async () => undefined),
}));
vi.mock("@/editor/EditorState", () => ({
  useDocumentEditor: () => ({ document: state.document, editor: { isDestroyed: false }, change: state.change, flush: state.flush }),
}));

function translationProposal(overrides: Partial<ProposedChange> = {}): ProposedChange {
  return {
    id: "t1",
    type: "replace_content",
    category: "translation",
    elementId: "p1",
    afterElementId: null,
    elementType: "paragraph",
    property: null,
    before: "Take 5 mg daily.",
    after: "Вземайте 5 мг дневно.",
    reason: `Translated into Bulgarian by ai. ${TRANSLATION_LABEL}`,
    source: "translation",
    confidence: null,
    createdAt: "2026-10-06T00:00:00Z",
    replacement: null,
    problems: [],
    targetLanguage: "bg",
    ...overrides,
  } as ProposedChange;
}

function documentWith(proposals: ProposedChange[] = [], metadata: object = {}): Document {
  return {
    id: "doc-1",
    metadata: { title: "Guide", language: null, translatedFrom: null, ...metadata },
    elements: [{ id: "p1", type: "paragraph", content: "Take 5 mg daily." }],
    proposals,
    glossary: [],
  } as unknown as Document;
}

afterEach(() => {
  Object.values(api).forEach((fn) => fn.mockClear());
  router.push.mockClear();
  state.change.mockClear();
});

describe("the Превод panel", () => {
  it("is always marked as AI-assisted and shows the detected language", async () => {
    state.document = documentWith();
    render(<TranslatePanel />);
    expect(screen.getByRole("note")).toHaveTextContent(TRANSLATION_LABEL);
    await waitFor(() => expect(screen.getByRole("option", { name: "English (detected)" })).toBeInTheDocument());
  });

  it("translates the selection into the chosen language as proposals, and says what was left as it was", async () => {
    state.document = documentWith();
    api.translateBlocks.mockResolvedValueOnce({
      document: documentWith([translationProposal()]),
      proposalCount: 1,
      sourceLanguage: "en",
      characters: 4,
      notTranslated: [{ elementId: "x", reasons: ["Bulgarian: a number differs from the original"] }],
      label: TRANSLATION_LABEL,
    });
    render(<TranslatePanel />);
    fireEvent.change(screen.getByLabelText("Translate into"), { target: { value: "de" } });
    fireEvent.click(screen.getByRole("button", { name: "Translate selection" }));

    await waitFor(() =>
      expect(api.translateBlocks).toHaveBeenCalledWith("doc-1", { elementIds: ["p1"], selection: { start: 0, end: 4 }, targetLanguage: "de", sourceLanguage: null }),
    );
    expect(state.flush).toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("1 block translated into German: review below.");
    expect(screen.getByRole("status")).toHaveTextContent("Left as it was: Bulgarian: a number differs from the original");
  });

  it("creates a translated version as a new document and opens it", async () => {
    state.document = documentWith([], { language: "en" });
    render(<TranslatePanel />);
    fireEvent.click(screen.getByRole("button", { name: "Create translated version" }));
    await waitFor(() => expect(api.translateDocument).toHaveBeenCalledWith("doc-1", "bg", "en", expect.any(Function)));
    expect(router.push).toHaveBeenCalledWith("/documents/doc-2");
  });

  it("sets the document's language when the user says what it is", async () => {
    state.document = documentWith();
    render(<TranslatePanel />);
    fireEvent.change(screen.getByLabelText("The document's language"), { target: { value: "fr" } });
    await waitFor(() => expect(api.setDocumentLanguage).toHaveBeenCalledWith("doc-1", "fr"));
  });

  it("saves the glossary's terms", async () => {
    state.document = documentWith();
    render(<TranslatePanel />);
    fireEvent.click(screen.getByRole("button", { name: "Add a term" }));
    fireEvent.change(screen.getByLabelText("Term 1"), { target: { value: "Aspirin" } });
    fireEvent.change(screen.getByLabelText("Translation 1"), { target: { value: "Аспирин" } });
    fireEvent.click(screen.getByRole("button", { name: "Save glossary" }));
    await waitFor(() =>
      expect(api.setGlossary).toHaveBeenCalledWith("doc-1", [
        { source: "Aspirin", target: "Аспирин", domain: null, locked: true, caseSensitive: false, sourceLanguage: null, targetLanguage: null },
      ]),
    );
  });
});

describe("a translation waiting for review", () => {
  it("shows the original against the translation and what was left as it was", () => {
    state.document = documentWith([translationProposal({ problems: ["Bulgarian: a unit of measure differs from the original"] })]);
    render(<ProposalsList source="translation" />);
    expect(screen.getByText("Translate a block into Bulgarian")).toBeInTheDocument();
    expect(screen.getByText("Take 5 mg daily.")).toBeInTheDocument();
    expect(screen.getByText("Вземайте 5 мг дневно.")).toBeInTheDocument();
    expect(screen.getByText("Left as it was: Bulgarian: a unit of measure differs from the original")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(TRANSLATION_LABEL))).toBeInTheDocument();
  });

  it("isn't listed among an instruction's changes", () => {
    state.document = documentWith([translationProposal()]);
    const { container } = render(<ProposalsList source="instruction" />);
    expect(container).toBeEmptyDOMElement();
  });
});
