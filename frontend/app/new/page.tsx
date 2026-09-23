"use client";

import { Suspense } from "react";

import { AppHeader } from "@/components/AppHeader";
import { CreateDocumentWizard } from "@/components/CreateDocumentWizard";

export default function NewDocumentPage() {
  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <Suspense fallback={null}>
        <CreateDocumentWizard />
      </Suspense>
    </div>
  );
}
