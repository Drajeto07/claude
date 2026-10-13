import { Suspense } from "react";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <AuthLayout>
      <Suspense fallback={null}>
        <AuthForm mode="login" />
      </Suspense>
    </AuthLayout>
  );
}
