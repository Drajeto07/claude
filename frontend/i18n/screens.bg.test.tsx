import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { ChangePasswordForm, DeleteAccountForm } from "@/components/AccountSettings";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { JobProgressBar } from "@/components/JobProgressBar";
import { TrackedChangesChoice } from "@/components/TrackedChangesChoice";
import { NumberField, ToggleField } from "@/components/templates/fields";
import { I18nProvider } from "@/i18n/I18nProvider";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/" }));

function inBulgarian(children: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider locale="bg">{children}</I18nProvider>
    </QueryClientProvider>,
  );
}

/** S2-017: the screens moved onto the dictionaries speak Bulgarian when the interface does. */
describe("old screens in Bulgarian", () => {
  it("changing the password", () => {
    inBulgarian(<ChangePasswordForm />);
    expect(screen.getByRole("heading", { name: "Смяна на паролата" })).toBeInTheDocument();
    expect(screen.getByLabelText("Текуща парола")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Смени паролата" })).toBeInTheDocument();
  });

  it("deleting the account asks for the phrase in Bulgarian", () => {
    inBulgarian(<DeleteAccountForm />);
    expect(screen.getByText("изтрий акаунта ми")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Изтрий акаунта ми" })).toBeDisabled();
  });

  it("a confirmation dialog", () => {
    inBulgarian(
      <ConfirmDialog title="Изтриване?" confirmLabel="Изтрий" onConfirm={() => undefined} onCancel={() => undefined}>
        <p>…</p>
      </ConfirmDialog>,
    );
    expect(screen.getByRole("button", { name: "Отказ" })).toHaveFocus();
  });

  it("a job's progress", () => {
    inBulgarian(<JobProgressBar progress={{ stage: "parsing", progress: 40 }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Четене на файла · 40%");
  });

  it("the tracked-changes choice", () => {
    inBulgarian(<TrackedChangesChoice choice="kept" onChoose={async () => undefined} />);
    expect(screen.getByRole("group", { name: "Проследени промени" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Приеми всички/ })).toBeInTheDocument();
  });

  it("template fields: “not set” and on/off", () => {
    inBulgarian(
      <>
        <NumberField label="Размер (pt)" value={null} onChange={() => undefined} />
        <ToggleField label="Удебелен" value={null} onChange={() => undefined} />
      </>,
    );
    expect(screen.getByLabelText("Размер (pt)")).toHaveAttribute("placeholder", "Не е зададено");
    expect(screen.getByRole("option", { name: "Включено" })).toBeInTheDocument();
  });
});
