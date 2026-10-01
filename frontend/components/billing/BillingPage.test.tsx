import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Billing, BillingPlan, Entitlements, UnitUsage } from "@/types/document";

import { BillingPage } from "./BillingPage";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }), usePathname: () => "/settings/billing" }));

const FREE: Entitlements = {
  canExportDocx: true,
  canExportPdf: true,
  maxDocuments: 25,
  maxDocumentSizeMb: 10,
  maxExports: 25,
  maxPdfPages: 20,
  maxOcrPages: 5,
  maxTranslationCharacters: 10000,
  maxBatchJobs: 0,
  maxAiOperations: 100,
  maxTemplates: 5,
  maxStorageMb: 250,
  priorityProcessing: false,
};

const MB = 1024 * 1024;

function unit(key: string, label: string, used: number, limit: number | null, extra: Partial<UnitUsage> = {}): UnitUsage {
  return { key, label, used, limit, period: "month", measure: "count", available: true, ...extra };
}

// As GET /billing lists them (backend billing/units.py).
const UNITS: UnitUsage[] = [
  unit("documents", "Documents", 8, 25, { period: "now" }),
  unit("exports", "Exports", 3, 25),
  unit("pdfPages", "PDF pages", 12, 20),
  unit("ocrPages", "OCR pages", 0, 5, { available: false }),
  unit("translationCharacters", "Translation characters", 0, 10000, { available: false }),
  unit("batchJobs", "Batch jobs", 0, 0, { available: false }),
  unit("aiOperations", "AI operations", 100, 100),
  unit("storageBytes", "Storage", 20 * MB, 250 * MB, { period: "now", measure: "bytes" }),
  unit("templates", "Templates of your own", 0, 5, { period: "now" }),
];

function plan(key: string, name: string, available: boolean, entitlements: Partial<Entitlements> = {}): BillingPlan {
  return { key, name, priceLabel: key === "free" ? "Free" : null, available, entitlements: { ...FREE, ...entitlements } };
}

function billing(overrides: Partial<Billing> = {}): Billing {
  const plans = [plan("free", "Free", false), plan("pro", "Pro", false, { maxDocuments: 500 }), plan("business", "Business", false, { maxDocuments: null })];
  return {
    plan: plans[0],
    status: null,
    currentPeriodEnd: null,
    cancelAtPeriodEnd: false,
    usage: {
      documents: { used: 8, limit: 25 },
      templates: { used: 0, limit: 5 },
      aiOperations: { used: 100, limit: 100 },
      storageBytes: { used: 20 * 1024 * 1024, limit: 250 * 1024 * 1024 },
    },
    units: UNITS,
    usagePeriodEnd: "2026-10-01T00:00:00Z",
    plans,
    billingEnabled: false,
    canManageBilling: false,
    ...overrides,
  };
}

/** The API as the page sees it: GET /api/billing, the signed-in user, and the Stripe redirects. */
function serve(data: Billing) {
  const calls: { url: string; method: string; body?: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = new URL(url).pathname;
      calls.push({ url: path, method: init.method ?? "GET", body: init.body as string | undefined });
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/api/v1/billing") return json(data);
      if (path === "/api/v1/auth/me") return json({ id: "u1", email: "boril@example.com", fullName: "Boril", workspaceId: "w1" });
      if (path === "/api/v1/billing/checkout") return json({ url: "https://checkout.stripe.test/c/1" });
      if (path === "/api/v1/billing/portal") return json({ url: "https://billing.stripe.test/p/1" });
      return new Response("{}", { status: 404 });
    }),
  );
  return calls;
}

function show(checkout: "success" | "cancelled" | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BillingPage checkout={checkout} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("BillingPage", () => {
  it("shows the plan, what is used of each limit, and that paid plans aren't available yet", async () => {
    serve(billing());
    show();

    expect(await screen.findByText("No subscription.")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Documents" })).toHaveAttribute("aria-valuenow", "8");
    expect(screen.getByText(/They renew on/)).toBeInTheDocument();
    expect(screen.getByText("Paid plans aren't available yet. Your plan's limits apply as shown.")).toBeInTheDocument();
    const pro = screen.getByRole("article", { name: "Pro plan" });
    expect(within(pro).getByText("Up to 500 documents")).toBeInTheDocument();
    expect(within(pro).getByRole("button", { name: "Not available yet" })).toBeDisabled();
    expect(within(screen.getByRole("article", { name: "Free plan" })).getByRole("button", { name: "Your plan" })).toBeDisabled();
  });

  it("shows every usage unit with the plan's limit, and the ones still to come apart", async () => {
    serve(billing());
    show();

    await screen.findByText("No subscription.");
    const meters = screen.getAllByRole("meter").map((meter) => [meter.getAttribute("aria-label"), meter.getAttribute("aria-valuenow"), meter.getAttribute("aria-valuemax")]);
    expect(meters).toEqual([
      ["Documents", "8", "25"],
      ["Exports this month", "3", "25"],
      ["PDF pages this month", "12", "20"],
      ["AI operations this month", "100", "100"],
      ["Storage", String(20 * MB), String(250 * MB)],
      ["Templates of your own", "0", "5"],
    ]);
    expect(screen.getByText("20 MB")).toBeInTheDocument();
    const later = within(screen.getByRole("heading", { name: "Coming later" }).parentElement as HTMLElement);
    expect(later.getByText("OCR pages").nextSibling).toHaveTextContent("5 a month");
    expect(later.getByText("Translation characters").nextSibling).toHaveTextContent("10,000 a month");
    expect(later.getByText("Batch jobs").nextSibling).toHaveTextContent("not included");
    const free = within(screen.getByRole("article", { name: "Free plan" }));
    expect(free.getByText("25 exports a month")).toBeInTheDocument();
    expect(free.getByText("20 PDF pages a month")).toBeInTheDocument();
  });

  it("sends an upgrade to Stripe Checkout", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const data = billing({ billingEnabled: true });
    data.plans[1].available = true;
    const calls = serve(data);
    show();

    await user.click(await screen.findByRole("button", { name: "Upgrade to Pro" }));

    expect(calls).toContainEqual({ url: "/api/v1/billing/checkout", method: "POST", body: '{"plan":"pro"}' });
    expect(assign).toHaveBeenCalledWith("https://checkout.stripe.test/c/1");
  });

  it("sends a subscriber to the billing portal to change plan", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const data = billing({ billingEnabled: true, canManageBilling: true, status: "active", currentPeriodEnd: "2026-10-26T07:33:20Z" });
    data.plan = data.plans[1];
    serve(data);
    show();

    expect(await screen.findByText(/Renews on/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    await user.click(within(screen.getByRole("article", { name: "Business plan" })).getByRole("button", { name: /Change in billing portal/ }));
    expect(assign).toHaveBeenCalledWith("https://billing.stripe.test/p/1");
  });

  it("warns about an overdue payment", async () => {
    const data = billing({ billingEnabled: true, canManageBilling: true, status: "past_due", currentPeriodEnd: "2026-10-26T07:33:20Z" });
    data.plan = data.plans[1];
    serve(data);
    show();

    expect(await screen.findByText(/Your last payment didn.t go through/)).toBeInTheDocument();
    expect(screen.getByText("Payment overdue")).toBeInTheDocument();
  });

  it("waits for Stripe after checkout, and says when a checkout was cancelled", async () => {
    serve(billing());
    show("success");
    expect(await screen.findByText(/Finishing your subscription/)).toBeInTheDocument();
  });

  it("says a cancelled checkout charged nothing", async () => {
    serve(billing());
    show("cancelled");
    expect(await screen.findByText("Checkout was cancelled. Nothing was charged.")).toBeInTheDocument();
  });
});
