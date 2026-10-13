import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { NewProject } from "@/components/projects/NewProject";
import { AppShell } from "@/components/shell/AppShell";
import { SESSION_COOKIE } from "@/services/api";

/**
 * Screen 3 of SmartDoc 2.0: choose what to create (S2-015). /new remains the document wizard.
 * It asks the API nothing, so no 401 would send a signed-out visitor to sign in: it does here.
 */
export default async function NewProjectPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await cookies()).get(SESSION_COOKIE)?.value) {
    const describe = (await searchParams).describe;
    const next = `/projects/new${typeof describe === "string" && describe ? `?describe=${encodeURIComponent(describe)}` : ""}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return (
    <AppShell>
      <Suspense fallback={null}>
        <NewProject />
      </Suspense>
    </AppShell>
  );
}
