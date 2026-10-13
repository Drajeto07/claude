import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api";

import { ForgotPasswordForm, ResetPasswordForm } from "./PasswordResetForms";

const api = vi.hoisted(() => ({ requestPasswordReset: vi.fn(), confirmPasswordReset: vi.fn(), getEmailDelivery: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const TOKEN = "Z3p4cXJzdHV2d3h5ejAxMjM0NTY3ODlhYmNkZWZnaGlq";

afterEach(() => {
  api.requestPasswordReset.mockReset();
  api.confirmPasswordReset.mockReset();
  api.getEmailDelivery.mockReset();
  window.history.replaceState(null, "", "/");
});

function withQueries(children: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>);
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe("asking for a reset link (ACCT-002)", () => {
  it("says what the server says, the same for any address", async () => {
    api.getEmailDelivery.mockResolvedValue(true);
    api.requestPasswordReset.mockResolvedValue("If an account uses that address, we've sent it a link.");
    withQueries(<ForgotPasswordForm />);

    fill("Email", "someone@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send the link" }));

    expect(await screen.findByRole("status")).toHaveTextContent("If an account uses that address");
    expect(api.requestPasswordReset).toHaveBeenCalledWith("someone@example.com");
  });

  it("says plainly that it isn't available while the server sends no e-mail, and offers no link (RELEASE)", async () => {
    api.getEmailDelivery.mockResolvedValue(false);
    withQueries(<ForgotPasswordForm />);

    expect(await screen.findByRole("status")).toHaveTextContent("Resetting a password isn't available yet");
    expect(screen.queryByRole("button", { name: "Send the link" })).toBeNull();
    expect(screen.queryByLabelText("Email")).toBeNull();
    expect(screen.getByRole("status")).not.toHaveTextContent("sent");
    expect(api.requestPasswordReset).not.toHaveBeenCalled();
  });
});

describe("choosing a new password with the link", () => {
  it("sends the link's token with the new password, then takes the token out of the address", async () => {
    window.history.replaceState(null, "", `/reset-password#token=${TOKEN}`);
    api.confirmPasswordReset.mockResolvedValue(undefined);
    render(<ResetPasswordForm />);

    fill("New password", "a new long password");
    fill("The same again", "a new long password");
    fireEvent.click(screen.getByRole("button", { name: "Save the new password" }));

    expect(await screen.findByRole("heading", { name: "Password changed" })).toBeInTheDocument();
    expect(api.confirmPasswordReset).toHaveBeenCalledWith(TOKEN, "a new long password");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/reset-password");
  });

  it("asks again when the two passwords differ, and sends nothing", () => {
    window.history.replaceState(null, "", `/reset-password#token=${TOKEN}`);
    render(<ResetPasswordForm />);

    fill("New password", "a new long password");
    fill("The same again", "a new long passwort");
    fireEvent.click(screen.getByRole("button", { name: "Save the new password" }));

    expect(screen.getByRole("alert")).toHaveTextContent("The two passwords aren't the same.");
    expect(api.confirmPasswordReset).not.toHaveBeenCalled();
  });

  it("keeps the token while the link didn't work, and says so", async () => {
    window.history.replaceState(null, "", `/reset-password#token=${TOKEN}`);
    api.confirmPasswordReset.mockRejectedValue(
      new ApiError(400, { code: "invalid_token", message: "This link has expired or has already been used. Ask for a new one." }, "", null),
    );
    render(<ResetPasswordForm />);

    fill("New password", "a new long password");
    fill("The same again", "a new long password");
    fireEvent.click(screen.getByRole("button", { name: "Save the new password" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This link has expired or has already been used."));
    expect(window.location.hash).toBe(`#token=${TOKEN}`);
  });

  it("says a link without its token is incomplete", () => {
    window.history.replaceState(null, "", "/reset-password");
    render(<ResetPasswordForm />);

    expect(screen.getByRole("alert")).toHaveTextContent("This link is incomplete.");
    expect(screen.queryByLabelText("New password")).toBeNull();
  });
});
