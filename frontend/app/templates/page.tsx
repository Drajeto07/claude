import type { Metadata } from "next";

import { TemplateLibrary } from "@/components/templates/TemplateLibrary";

export const metadata: Metadata = { title: "Templates · SmartDoc Formatter" };

export default function TemplatesPage() {
  return <TemplateLibrary />;
}
