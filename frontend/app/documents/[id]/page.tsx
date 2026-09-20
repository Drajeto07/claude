import { notFound } from "next/navigation";

import { DocumentEditor } from "@/components/DocumentEditor";
import { getDocument } from "@/services/api";

export default async function DocumentPage({ params }: PageProps<"/documents/[id]">) {
  const { id } = await params;

  let document;
  try {
    document = await getDocument(id);
  } catch {
    notFound();
  }

  return <DocumentEditor initialDocument={document} />;
}
