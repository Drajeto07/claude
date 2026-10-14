import type { Metadata } from "next";

import { pageMetadata } from "@/i18n/server";

import { BillingPage } from "@/components/billing/BillingPage";

export const generateMetadata = (): Promise<Metadata> => pageMetadata((m) => m.billing.title);

/** Stripe sends the user back here with ?checkout=success or ?checkout=cancelled. */
export default async function BillingSettingsPage({ searchParams }: PageProps<"/settings/billing">) {
  const { checkout } = await searchParams;
  return <BillingPage checkout={checkout === "success" || checkout === "cancelled" ? checkout : null} />;
}
