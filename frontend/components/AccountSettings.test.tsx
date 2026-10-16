import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api";
import type { SignedInSession } from "@/types/document";

import { ChangePasswordForm, DeleteAccountForm, SessionsList } from "./AccountSettings";

const api = vi.hoisted(() => ({
  changePassword: vi.fn(),
  deleteAccount: vi.fn(),
  listSessions: vi.fn(),
  signOutSession: vi.fn(),
  signOutOtherSessions: vi.fn(),
}));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

afterEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  vi.unstubAllGlobals();
});

function withQueries(children: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>);
}

function fill(current: string, next: string, repeated = next) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: current } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("The new one again"), { target: { value: repeated } });
  fireEvent.click(screen.getByRole("button", { name: "Change the password" }));
}

describe("changing the password (ACCT-004)", () => {
  it("sends the current and the new one, says it's done and clears the fields", async () => {
    api.changePassword.mockResolvedValue(undefined);
    render(<ChangePasswordForm />);

    fill("my old password", "my new long password");

    expect(await screen.findByRole("status")).toHaveTextContent("Your password is changed.");
    expect(api.changePassword).toHaveBeenCalledWith("my old password", "my new long password");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
  });

  it("asks again when the two new ones differ, and sends nothing", () => {
    render(<ChangePasswordForm />);

    fill("my old password", "my new long password", "my new long passwort");

    expect(screen.getByRole("alert")).toHaveTextContent("The two new passwords aren't the same.");
    expect(api.changePassword).not.toHaveBeenCalled();
  });

  it("says when the current password isn't right", async () => {
    api.changePassword.mockRejectedValue(new ApiError(400, { code: "wrong_password", message: "That isn't your current password." }, "", null));
    render(<ChangePasswordForm />);

    fill("a guess", "my new long password");

    expect(await screen.findByRole("alert")).toHaveTextContent("That isn't your current password.");
    expect(screen.queryByRole("status")).toBeNull();
  });
});

const THIS: SignedInSession = { id: "s1", browser: "Firefox on Windows", createdAt: "2026-09-30T10:00:00Z", lastUsedAt: "2026-10-01T09:00:00Z", current: true };
const PHONE: SignedInSession = { id: "s2", browser: "Safari on iPhone", createdAt: "2026-09-29T10:00:00Z", lastUsedAt: null, current: false };

describe("the browsers signed in (ACCT-006)", () => {
  it("lists each browser by name, marks this one and signs another out", async () => {
    api.listSessions.mockResolvedValueOnce([THIS, PHONE]).mockResolvedValue([THIS]);
    api.signOutSession.mockResolvedValue(undefined);
    withQueries(<SessionsList />);

    const phone = (await screen.findByText("Safari on iPhone")).closest("li")!;
    expect(screen.getByText("This browser")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out Firefox on Windows" })).toBeNull();
    fireEvent.click(within(phone).getByRole("button", { name: "Sign out Safari on iPhone" }));

    expect(api.signOutSession).toHaveBeenCalledWith("s2");
    expect(await screen.findByText("Firefox on Windows")).toBeInTheDocument();
    await vi.waitFor(() => expect(screen.queryByText("Safari on iPhone")).toBeNull());
    expect(screen.queryByRole("button", { name: "Sign out every other browser" })).toBeNull();
  });

  it("signs out every other browser at once", async () => {
    api.listSessions.mockResolvedValueOnce([THIS, PHONE]).mockResolvedValue([THIS]);
    api.signOutOtherSessions.mockResolvedValue(undefined);
    withQueries(<SessionsList />);

    fireEvent.click(await screen.findByRole("button", { name: "Sign out every other browser" }));

    expect(api.signOutOtherSessions).toHaveBeenCalled();
    await vi.waitFor(() => expect(screen.queryByText("Safari on iPhone")).toBeNull());
  });
});

describe("deleting the account (ACCT-005)", () => {
  function fill(password: string, typed: string) {
    fireEvent.change(screen.getByLabelText("Your password"), { target: { value: password } });
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: typed } });
  }

  it("says what goes and waits for the typed confirmation", () => {
    render(<DeleteAccountForm />);

    expect(screen.getByText(/your documents, their versions, pictures and kept originals/)).toBeInTheDocument();
    fill("my password", "delete my acount");

    expect(screen.getByRole("button", { name: "Delete my account" })).toBeDisabled();
    expect(api.deleteAccount).not.toHaveBeenCalled();
  });

  it("sends the password, then goes to the sign-in page that says so", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    api.deleteAccount.mockResolvedValue(undefined);
    render(<DeleteAccountForm />);

    fill("my password", "Delete my account");
    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login?deleted=1"));
    expect(api.deleteAccount).toHaveBeenCalledWith("my password");
  });

  it("says why when it is refused, and stays", async () => {
    api.deleteAccount.mockRejectedValue(
      new ApiError(409, { code: "subscription_active", message: "Your plan still renews. Cancel it in Plan and billing first, then delete your account." }, "", null),
    );
    render(<DeleteAccountForm />);

    fill("my password", "delete my account");
    fireEvent.click(screen.getByRole("button", { name: "Delete my account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Your plan still renews.");
    expect(screen.getByRole("button", { name: "Delete my account" })).toBeEnabled();
  });
});
