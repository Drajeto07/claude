import { Suspense } from "react";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { AuthForm } from "@/components/AuthForm";

export default function RegisterPage() {
  return (
    <AuthLayout>
      <Suspense fallback={null}>
        <AuthForm mode="register" />
      </Suspense>
    </AuthLayout>
  );
}
