import type { Metadata } from "next";

import { pageMetadata } from "@/i18n/server";

import { AccountSettings } from "@/components/AccountSettings";

export const generateMetadata = (): Promise<Metadata> => pageMetadata((m) => m.account.title);

export default function AccountSettingsPage() {
  return <AccountSettings />;
}
