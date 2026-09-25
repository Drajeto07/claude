import type { Metadata } from "next";

import { DocumentList } from "@/components/documents/DocumentList";

export const metadata: Metadata = { title: "Documents · SmartDoc Formatter" };

export default function DocumentsPage() {
  return <DocumentList />;
}
