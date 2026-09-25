import type { Metadata } from "next";

import { BillingPage } from "@/components/billing/BillingPage";

export const metadata: Metadata = { title: "Plan and billing · SmartDoc Formatter" };

/** Stripe sends the user back here with ?checkout=success or ?checkout=cancelled. */
export default async function BillingSettingsPage({ searchParams }: PageProps<"/settings/billing">) {
  const { checkout } = await searchParams;
  return <BillingPage checkout={checkout === "success" || checkout === "cancelled" ? checkout : null} />;
}
