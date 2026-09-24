import { Suspense } from "react";

import { AppHeader } from "@/components/AppHeader";
import { AuthForm } from "@/components/AuthForm";

export default function RegisterPage() {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="flex flex-1 items-center justify-center px-6 py-16">
        <Suspense fallback={null}>
          <AuthForm mode="register" />
        </Suspense>
      </main>
    </div>
  );
}
