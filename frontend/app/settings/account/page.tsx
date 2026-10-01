import type { Metadata } from "next";

import { AccountSettings } from "@/components/AccountSettings";

export const metadata: Metadata = { title: "Your account · SmartDoc Formatter" };

export default function AccountSettingsPage() {
  return <AccountSettings />;
}
