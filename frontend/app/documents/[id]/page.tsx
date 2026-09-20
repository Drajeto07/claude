import { notFound } from "next/navigation";

import { DocumentEditor } from "@/components/DocumentEditor";
import { getDocument } from "@/services/api";

export default async function DocumentPage({ params }: PageProps<"/documents/[id]">) {
  const { id } = await params;

  try {
    const document = await getDocument(id);
    return <DocumentEditor initialDocument={document} />;
  } catch {
    notFound();
  }
}
