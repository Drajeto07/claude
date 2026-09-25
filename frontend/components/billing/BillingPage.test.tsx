import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Billing, BillingPlan, Entitlements } from "@/types/document";

import { BillingPage } from "./BillingPage";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }), usePathname: () => "/settings/billing" }));

const FREE: Entitlements = {
  canExportDocx: true,
  canExportPdf: true,
  maxDocuments: 25,
  maxDocumentSizeMb: 10,
  maxAiOperations: 100,
  maxTemplates: 5,
  maxStorageMb: 250,
  priorityProcessing: false,
};

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
      if (path === "/api/billing") return json(data);
      if (path === "/api/auth/me") return json({ id: "u1", email: "boril@example.com", fullName: "Boril", workspaceId: "w1" });
      if (path === "/api/billing/checkout") return json({ url: "https://checkout.stripe.test/c/1" });
      if (path === "/api/billing/portal") return json({ url: "https://billing.stripe.test/p/1" });
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

  it("sends an upgrade to Stripe Checkout", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const data = billing({ billingEnabled: true });
    data.plans[1].available = true;
    const calls = serve(data);
    show();

    await user.click(await screen.findByRole("button", { name: "Upgrade to Pro" }));

    expect(calls).toContainEqual({ url: "/api/billing/checkout", method: "POST", body: '{"plan":"pro"}' });
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
