import type { Metadata } from "next";

import { pageMetadata } from "@/i18n/server";

import { DocumentList } from "@/components/documents/DocumentList";

export const generateMetadata = (): Promise<Metadata> => pageMetadata((m) => m.documents.title);

export default function DocumentsPage() {
  return <DocumentList />;
}
