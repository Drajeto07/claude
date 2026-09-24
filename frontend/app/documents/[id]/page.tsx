import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import { DocumentEditor } from "@/components/DocumentEditor";
import { getDocument, SESSION_COOKIE, UnauthorizedError } from "@/services/api";

export default async function DocumentPage({ params }: PageProps<"/documents/[id]">) {
  const { id } = await params;
  const loginUrl = `/login?next=${encodeURIComponent(`/documents/${id}`)}`;

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

  return <DocumentEditor initialDocument={document} />;
}
