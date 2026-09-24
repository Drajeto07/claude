import type { Metadata } from "next";

import { TemplateEditor } from "@/components/templates/TemplateEditor";

export const metadata: Metadata = { title: "Template · SmartDoc Formatter" };

export default async function TemplatePage({ params }: PageProps<"/templates/[id]">) {
  const { id } = await params;
  // Keyed, so opening a duplicate starts from a clean editor instead of the previous template's state.
  return <TemplateEditor key={id} templateId={id} />;
}
