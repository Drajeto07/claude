import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";

const nav = vi.hoisted(() => ({ pathname: "/documents" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("@/services/queries", () => ({
  useCurrentUser: () => ({ data: { id: "u1", email: "dana@example.com", fullName: "Dana Petrova", workspaceId: "w1", emailVerified: false } }),
}));

afterEach(() => {
  nav.pathname = "/documents";
});

describe("the signed-in shell (S2-013)", () => {
  it("offers Create project and the main places, marking the current one", () => {
    render(<AppShell>page</AppShell>);

    const main = screen.getAllByRole("navigation", { name: "Main" })[0];
    expect(within(main).getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
    expect(within(main).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current");
    expect(screen.getAllByRole("link", { name: /Create project/ })[0]).toHaveAttribute("href", "/projects/new");  // screen 3 (S2-015)
    expect(screen.getByText("page")).toBeInTheDocument();
  });

  it("Home is current only on the home page itself", () => {
    nav.pathname = "/";
    render(<AppShell>page</AppShell>);
    const main = screen.getAllByRole("navigation", { name: "Main" })[0];
    expect(within(main).getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    expect(within(main).getByRole("link", { name: "Projects" })).not.toHaveAttribute("aria-current");
  });

  it("names who is signed in and lets them sign out", () => {
    render(<AppShell>page</AppShell>);
    expect(screen.getAllByText("Dana Petrova").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Sign out" }).length).toBe(1);  // one, not one per copy of the menu
  });

  it("on phones the menu opens as a dialog and closes with Escape", () => {
    render(<AppShell>page</AppShell>);
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Open the menu" }));
    const dialog = screen.getByRole("dialog", { name: "Menu" });
    expect(within(dialog).getByRole("link", { name: "Templates" })).toBeInTheDocument();
    expect(within(dialog).getAllByRole("button", { name: "Close the menu" })[0]).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Menu" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open the menu" })).toHaveFocus();  // focus goes back to the button
  });
});
