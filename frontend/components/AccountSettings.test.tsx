import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api";

import { ChangePasswordForm } from "./AccountSettings";

const api = vi.hoisted(() => ({ changePassword: vi.fn() }));
vi.mock("@/services/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));

afterEach(() => api.changePassword.mockReset());

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
