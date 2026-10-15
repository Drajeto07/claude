import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { DocumentEditorShell } from "@/editor/DocumentEditorShell";
import { EditorShellV2 } from "@/editor/v2/EditorShellV2";
import { getDocument, SESSION_COOKIE, UnauthorizedError } from "@/services/api";

/** The editor. The 1.x shell is the default; `?editor=2` opens the SmartDoc 2.0 shell (E1, preview) on the same
 * engine, so the same document can be opened in either. */
export default async function DocumentPage({ params, searchParams }: PageProps<"/documents/[id]">) {
  const { id } = await params;
  const query = await searchParams;
  const v2 = query.editor === "2";
  const here = `/documents/${id}${v2 ? "?editor=2" : ""}`;
  const loginUrl = `/login?next=${encodeURIComponent(here)}`;

  // This renders on the Next.js server, which has no browser cookie jar, so the
  // incoming request's session cookie is forwarded to the API explicitly.
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) redirect(loginUrl);

  let document;
  let signedOut = false;
  try {
    document = await getDocument(id, session);
  } catch (error) {
    if (!(error instanceof UnauthorizedError)) notFound();
    signedOut = true;
  }
  // redirect() works by throwing, so it must stay outside the try/catch above.
  if (signedOut || !document) redirect(loginUrl);

  return v2 ? <EditorShellV2 initialDocument={document} doctor={query.doctor === "1"} /> : <DocumentEditorShell initialDocument={document} />;
}
