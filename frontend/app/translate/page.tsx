import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/shell/AppShell";
import { TranslatePlanned } from "@/components/translate/TranslatePlanned";
import { SESSION_COOKIE } from "@/services/api";

/** Translate (S2-070): the planned flow, honestly marked as not available yet. Signed in only. */
export default async function TranslatePage() {
  if (!(await cookies()).get(SESSION_COOKIE)?.value) redirect("/login?next=%2Ftranslate");
  return (
    <AppShell>
      <TranslatePlanned />
    </AppShell>
  );
}
