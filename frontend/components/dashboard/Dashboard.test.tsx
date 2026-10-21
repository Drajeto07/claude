import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";

import { Dashboard } from "./Dashboard";

const nav = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => nav }));

const project = (id: string, title: string, extra: object = {}) => ({
  id,
  title,
  createdAt: "2026-10-10T10:00:00Z",
  updatedAt: new Date(Date.now() - 5 * 60_000).toISOString(),
  formattedAt: null,
  status: "draft",
  sourceType: "uploaded_docx",
  originalFilename: null,
  templateId: null,
  templateName: null,
  ...extra,
});

const state = vi.hoisted(() => ({
  list: vi.fn(),
  lastParams: [] as object[],
}));

vi.mock("@/services/queries", () => ({
  useCurrentUser: () => ({ data: { id: "u1", email: "dana@example.com", fullName: "Dana", workspaceId: "w1", emailVerified: true } }),
  useDocumentList: (params: object) => {
    state.lastParams.push(params);
    return state.list(params);
  },
  useUsage: () => ({ isPending: false, isError: false, data: { documents: 3, aiOperations: 1, exports: 2 } }),
  useBilling: () => ({ data: { plan: { name: "Free" }, usage: { documents: { limit: 25 }, aiOperations: { limit: 100 } } } }),
  useRecentExports: () => ({ isPending: false, isError: false, data: [] }),
  useTemplates: () => ({ isPending: false, data: [{ id: "professional-cv", name: "Професионален (CV)", builtin: true, isDefault: false }] }),
  useEmailDelivery: () => ({ data: false }),
}));

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  state.lastParams = [];
  state.list.mockImplementation(() => ({ isPending: false, isError: false, data: { items: [project("d1", "Annual report"), project("d2", "Wedding menu", { status: "formatted", sourceType: "pasted_text", templateName: "Modern" })], total: 2 } }));
});

afterEach(() => {
  vi.useRealTimers();
  state.list.mockReset();
  nav.push.mockReset();
});

function renderDashboard(locale: "en" | "bg" = "en") {
  return render(
    <I18nProvider locale={locale}>
      <Dashboard />
    </I18nProvider>,
  );
}

describe("the dashboard (S2-014)", () => {
  it("welcomes by name and shows the projects as cards that open them", () => {
    renderDashboard();
    expect(screen.getByRole("heading", { level: 1, name: "Welcome back, Dana" })).toBeInTheDocument();
    const gallery = screen.getByRole("region", { name: "Recent projects" });
    const report = within(gallery).getByRole("link", { name: /Annual report/ });
    expect(report).toHaveAttribute("href", "/documents/d1");
    expect(report).toHaveTextContent("Document · Word file");
    expect(report).toHaveTextContent("Edited 5 minutes ago");
    expect(report).toHaveTextContent("Draft");
    expect(within(gallery).getByRole("link", { name: /Wedding menu/ })).toHaveTextContent("Formatted");
  });

  it("searches as you pause typing, once, with what you typed", () => {
    renderDashboard();
    fireEvent.change(screen.getByLabelText("Search your projects"), { target: { value: "  report " } });
    expect(state.lastParams.at(-1)).toEqual({ q: undefined, limit: 9 });  // not on every key

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(state.lastParams.at(-1)).toEqual({ q: "report", limit: 9 });
  });

  it("says when nothing matches, and offers the first project when there are none", () => {
    state.list.mockImplementation((params: { q?: string }) => ({ isPending: false, isError: false, data: { items: [], total: 0, q: params.q } }));
    renderDashboard();
    expect(screen.getByText("No projects yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your first project" })).toHaveAttribute("href", "/projects/new");

    fireEvent.change(screen.getByLabelText("Search your projects"), { target: { value: "zzz" } });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByText("No projects match “zzz”.")).toBeInTheDocument();
  });

  it("when the projects can't load: says so and lets you try again", () => {
    const refetch = vi.fn();
    state.list.mockImplementation(() => ({ isPending: false, isError: true, refetch }));
    renderDashboard();
    expect(screen.getByRole("alert")).toHaveTextContent("Your projects couldn't be loaded.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("while loading: a placeholder that says what it is waiting for", () => {
    state.list.mockImplementation(() => ({ isPending: true, isError: false }));
    renderDashboard();
    expect(screen.getByText("Loading your projects…")).toBeInTheDocument();
  });

  it("describing a project takes it to New Project with the description", () => {
    renderDashboard();
    fireEvent.change(screen.getByLabelText("What do you want to create?"), { target: { value: "a poster for a concert" } });
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(nav.push).toHaveBeenCalledWith("/projects/new?describe=a%20poster%20for%20a%20concert");
  });

  it("the idea panel says plainly what works now and what comes later", () => {
    renderDashboard();
    expect(screen.getByText("Works now: SmartDoc suggests a project type from your words.")).toBeInTheDocument();
    expect(screen.getByText("Coming: AI that drafts the first version for you to approve.")).toBeInTheDocument();
  });

  it("Translate is a quick start of its own, marked as coming", () => {
    renderDashboard();
    const translate = within(screen.getByRole("main")).getByRole("link", { name: /^Translate/ });
    expect(translate).toHaveAttribute("href", "/translate");
    expect(translate).toHaveTextContent("Coming soon");
  });

  it("the plan, exports and templates stay, in one quiet column", () => {
    renderDashboard();
    const glance = screen.getByRole("complementary", { name: "At a glance" });
    expect(glance).toHaveTextContent("3 of 25 documents");
    expect(screen.getByRole("meter", { name: "Your plan" })).toHaveAttribute("aria-valuenow", "3");
    expect(glance).toHaveTextContent("Nothing exported recently.");
    expect(glance).toHaveTextContent("Professional (CV)"); // a built-in template, named in the interface's language (S2-028)
  });

  it("in Bulgarian, every word of the screen is Bulgarian", () => {
    renderDashboard("bg");
    expect(screen.getByRole("heading", { level: 1, name: "Добре дошли отново, Dana" })).toBeInTheDocument();
    const gallery = screen.getByRole("region", { name: "Последни проекти" });
    expect(within(gallery).getByRole("link", { name: /Annual report/ })).toHaveTextContent("Документ · Word файл");
    expect(within(gallery).getByRole("link", { name: /Annual report/ })).toHaveTextContent("Редактиран преди 5 минути");
    expect(screen.getByText("Документи: 3 от 25")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Нов проект/ }).length).toBeGreaterThan(0);
    expect(screen.getByRole("complementary", { name: "Накратко" })).toHaveTextContent("Професионален (CV)");
  });
});
