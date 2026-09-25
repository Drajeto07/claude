import { apiFetch, jsonInit, jsonOrThrow } from "@/services/api/client";
import type { Billing, BillingRedirect } from "@/types/document";

/** The workspace's plan, what it has used of the plan's limits, and the plans there are. */
export async function getBilling(): Promise<Billing> {
  return jsonOrThrow(await apiFetch("/api/billing", { cache: "no-store" }), "Couldn't load your plan");
}

/** The address of a Stripe Checkout page for subscribing to `plan`. The plan
 * changes once Stripe tells the backend, a few seconds after paying. */
export async function startCheckout(plan: string): Promise<string> {
  const { url } = await jsonOrThrow<BillingRedirect>(await apiFetch("/api/billing/checkout", jsonInit("POST", { plan })), "Couldn't open the payment page");
  return url;
}

/** The address of Stripe's billing portal: change plan, update the card, see invoices, cancel. */
export async function openBillingPortal(): Promise<string> {
  const { url } = await jsonOrThrow<BillingRedirect>(await apiFetch("/api/billing/portal", { method: "POST" }), "Couldn't open the billing portal");
  return url;
}
