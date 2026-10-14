import type { Metadata } from "next";

import { pageMetadata } from "@/i18n/server";

import { TemplateLibrary } from "@/components/templates/TemplateLibrary";

export const generateMetadata = (): Promise<Metadata> => pageMetadata((m) => m.templatesPage.title);

export default function TemplatesPage() {
  return <TemplateLibrary />;
}
