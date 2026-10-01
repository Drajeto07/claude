import { AppHeader } from "@/components/AppHeader";
import { ForgotPasswordForm } from "@/components/PasswordResetForms";

export default function ForgotPasswordPage() {
  return (
    <div className="flex flex-1 flex-col bg-zinc-50 dark:bg-black">
      <AppHeader />
      <main className="flex flex-1 items-center justify-center px-6 py-16">
        <ForgotPasswordForm />
      </main>
    </div>
  );
}
