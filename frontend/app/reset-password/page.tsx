import type { Metadata } from "next";

import { AppHeader } from "@/components/AppHeader";
import { ResetPasswordForm } from "@/components/PasswordResetForms";

// The link's token is in the fragment, which no request carries; and nothing on this page may tell another site it was opened.
export const metadata: Metadata = { referrer: "no-referrer" };

export default function ResetPasswordPage() {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="flex flex-1 items-center justify-center px-6 py-16">
        <ResetPasswordForm />
      </main>
    </div>
  );
}
