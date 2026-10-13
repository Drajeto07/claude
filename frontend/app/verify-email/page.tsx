import type { Metadata } from "next";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { VerifyEmailForm } from "@/components/VerifyEmail";

// The link's token is in the fragment, which no request carries; and nothing on this page may tell another site it was opened.
export const metadata: Metadata = { referrer: "no-referrer" };

export default function VerifyEmailPage() {
  return (
    <AuthLayout>
      <VerifyEmailForm />
    </AuthLayout>
  );
}
