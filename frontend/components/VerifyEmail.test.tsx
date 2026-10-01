import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api";
import { queryKeys } from "@/services/queries";

import { VerifyEmailBanner, VerifyEmailForm } from "./VerifyEmail";

const api = vi.hoisted(() => ({ requestEmailVerification: vi.fn(), confirmEmailVerification: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

const TOKEN = "dmVyaWZ5LXRoaXMtYWRkcmVzcy1wbGVhc2UtMDEyMzQ1Ng";

afterEach(() => {
  api.requestEmailVerification.mockReset();
  api.confirmEmailVerification.mockReset();
  window.history.replaceState(null, "", "/");
});

function withQueries(children: ReactNode, client = new QueryClient()) {
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

describe("the notice while an address isn't confirmed (ACCT-003)", () => {
  it("names the address, and sends another link on request", async () => {
    api.requestEmailVerification.mockResolvedValue("We've sent a link to your address.");
    render(<VerifyEmailBanner email="erin@example.com" />);

    expect(screen.getByRole("region", { name: "Confirm your e-mail address" })).toHaveTextContent("we sent a link to erin@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send the link again" }));

    expect(await screen.findByText("We've sent a link to your address.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send the link again" })).toBeNull();
  });
});

describe("the page the link opens", () => {
  it("confirms with one click, takes the token out of the address and asks who is signed in again", async () => {
    window.history.replaceState(null, "", `/verify-email#token=${TOKEN}`);
    api.confirmEmailVerification.mockResolvedValue(undefined);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    withQueries(<VerifyEmailForm />, client);

    expect(api.confirmEmailVerification).not.toHaveBeenCalled(); // opening the link confirms nothing
    fireEvent.click(screen.getByRole("button", { name: "Confirm my address" }));

    expect(await screen.findByRole("heading", { name: "Address confirmed" })).toBeInTheDocument();
    expect(api.confirmEmailVerification).toHaveBeenCalledWith(TOKEN);
    expect(window.location.hash).toBe("");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.currentUser });
  });

  it("says when the link no longer works", async () => {
    window.history.replaceState(null, "", `/verify-email#token=${TOKEN}`);
    api.confirmEmailVerification.mockRejectedValue(new ApiError(400, { code: "invalid_token", message: "This link has expired." }, "", null));
    withQueries(<VerifyEmailForm />);

    fireEvent.click(screen.getByRole("button", { name: "Confirm my address" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This link has expired."));
  });

  it("says a link without its token is incomplete", () => {
    window.history.replaceState(null, "", "/verify-email");
    withQueries(<VerifyEmailForm />);

    expect(screen.getByRole("alert")).toHaveTextContent("This link is incomplete.");
    expect(screen.queryByRole("button", { name: "Confirm my address" })).toBeNull();
  });
});
