import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { DocumentFlow } from "@/components/projects/create/DocumentFlow";
import { AppShell } from "@/components/shell/AppShell";
import { SESSION_COOKIE } from "@/services/api";

/**
 * The document flow of SmartDoc 2.0 (S2-020): content, structure, look, editor. Same address as the 1.x
 * wizard it replaces, so every link (?template=, ?mode=upload, ?reference=1) keeps working. Signed out:
 * to sign in and back.
 */
export default async function NewDocumentPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!(await cookies()).get(SESSION_COOKIE)?.value) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(await searchParams)) if (typeof value === "string") query.set(key, value);
    const next = `/new${query.size ? `?${query}` : ""}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return (
    <AppShell>
      <Suspense fallback={null}>
        <DocumentFlow />
      </Suspense>
    </AppShell>
  );
}
