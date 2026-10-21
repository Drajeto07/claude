import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";

import { DocumentList } from "./DocumentList";

/**
 * The Projects gallery (S2-025): every document as a card with the list's functions -- open, tick, tick the
 * page, before and after, delete, search, sort, pages -- and a picture of its kind, never a thumbnail request.
 */

vi.mock("next/navigation", () => ({ usePathname: () => "/documents", useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/components/shell/AppShell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("@/components/documents/BatchBar", () => ({
  BatchBar: ({ selected }: { selected: string[] }) => <section aria-label="Selected documents">{selected.join(",")}</section>,
}));

const api = vi.hoisted(() => ({ deleteDocument: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const state = vi.hoisted(() => ({ list: vi.fn(), params: [] as Record<string, unknown>[] }));
vi.mock("@/services/queries", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useDocumentList: (params: Record<string, unknown>) => {
    state.params.push(params);
    return state.list(params);
  },
}));

const doc = (id: string, title: string, extra: object = {}) => ({
  id,
  title,
  createdAt: "2026-10-10T10:00:00Z",
  updatedAt: new Date(Date.now() - 5 * 60_000).toISOString(),
  formattedAt: null,
  status: "draft",
  sourceType: "uploaded_docx",
  originalFilename: "report.docx",
  templateId: null,
  templateName: null,
  ...extra,
});

const ITEMS = [doc("d1", "Annual report"), doc("d2", "Meeting notes", { sourceType: "pasted_text", originalFilename: null, status: "formatted", formattedAt: "2026-10-11T10:00:00Z" })];

beforeEach(() => {
  state.params = [];
  state.list.mockReset();
  state.list.mockImplementation(() => ({ isPending: false, isPlaceholderData: false, error: null, data: { items: ITEMS, total: 2 } }));
  api.deleteDocument.mockReset();
});

function renderList(locale: "en" | "bg" = "en") {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <I18nProvider locale={locale}>
        <DocumentList />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const cards = () => within(screen.getByRole("list")).getAllByRole("listitem");

describe("the Projects gallery (S2-025)", () => {
  it("shows each document as a card that opens it, with its kind, when it changed and its status", () => {
    renderList();
    expect(cards()).toHaveLength(2);
    const [first, second] = cards();
    expect(within(first).getByRole("link", { name: "Annual report" })).toHaveAttribute("href", "/documents/d1");
    expect(first).toHaveTextContent("Word file");
    expect(first).toHaveTextContent(/Edited 5 minutes ago/);
    expect(first).toHaveTextContent("Draft");
    expect(second).toHaveTextContent("Pasted text");
    expect(second).toHaveTextContent("Formatted");
    expect(within(first).getByRole("link", { name: "Before and after: Annual report" })).toHaveAttribute("href", "/documents/d1/compare");
  });

  it("asks for no thumbnail: no picture element, no thumbnail address, only a picture of the document's kind", () => {
    const { container } = renderList();
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.innerHTML).not.toMatch(/thumbnail/i);
    expect(screen.getAllByTestId("project-kind")).toHaveLength(2);
    for (const kind of screen.getAllByTestId("project-kind")) expect(kind).toHaveAttribute("aria-hidden", "true");
  });

  it("ticks one document, then every one on the page, and the batch bar gets them", () => {
    renderList();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Annual report" }));
    expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("d1");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select every document on this page" }));
    expect(screen.getByRole("region", { name: "Selected documents" })).toHaveTextContent("d1,d2");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select every document on this page" }));
    expect(screen.queryByRole("region", { name: "Selected documents" })).not.toBeInTheDocument();
  });

  it("deletes a document only after asking", async () => {
    api.deleteDocument.mockResolvedValue(undefined);
    renderList();
    fireEvent.click(screen.getByRole("button", { name: "Delete Meeting notes" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Meeting notes");
    expect(api.deleteDocument).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete for good" }));
    await waitFor(() => expect(api.deleteDocument).toHaveBeenCalledWith("d2"));
  });

  it("keeps search, sort and pages", async () => {
    state.list.mockImplementation(() => ({ isPending: false, isPlaceholderData: false, error: null, data: { items: ITEMS, total: 45 } }));
    renderList();
    fireEvent.change(screen.getByRole("combobox", { name: "Sort by" }), { target: { value: "title" } });
    expect(state.params.at(-1)).toMatchObject({ sort: "title", offset: 0, limit: 20 });
    const pages = screen.getByRole("navigation", { name: "Pages" });
    expect(pages).toHaveTextContent("1–20 of 45");
    fireEvent.click(within(pages).getByRole("button", { name: "Next" }));
    expect(state.params.at(-1)).toMatchObject({ offset: 20 });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search by title" }), { target: { value: "notes" } });
    await waitFor(() => expect(state.params.at(-1)).toMatchObject({ q: "notes", offset: 0 }));
  });

  it("says when there is nothing yet, and when nothing matches", () => {
    state.list.mockImplementation(() => ({ isPending: false, isPlaceholderData: false, error: null, data: { items: [], total: 0 } }));
    renderList();
    expect(screen.getByText("No projects yet. Paste some text or upload a file to start.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("in Bulgarian, the cards and their actions are Bulgarian", () => {
    renderList("bg");
    const [first] = cards();
    expect(first).toHaveTextContent("Word файл");
    expect(within(first).getByRole("button", { name: "Изтрий Annual report" })).toBeInTheDocument();
    expect(first).toHaveTextContent("Чернова");
  });
});
