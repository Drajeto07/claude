import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PLAN_LIMIT_EVENT } from "@/services/api";

import { PlanLimitBanner } from "./PlanLimitBanner";

const navigation = vi.hoisted(() => ({ pathname: "/documents" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));

function refuse(message: string) {
  act(() => {
    window.dispatchEvent(new CustomEvent(PLAN_LIMIT_EVENT, { detail: message }));
  });
}

describe("PlanLimitBanner", () => {
  beforeEach(() => {
    navigation.pathname = "/documents";
  });

  it("stays out of the way until the plan refuses something", () => {
    render(<PlanLimitBanner />);

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says what was refused and offers the plans", () => {
    render(<PlanLimitBanner />);

    refuse("Your plan allows 25 documents.");

    expect(screen.getByRole("status")).toHaveTextContent("Your plan allows 25 documents.");
    expect(screen.getByRole("link", { name: "See plans and usage" })).toHaveAttribute("href", "/settings/billing");
  });

  it("goes when dismissed, and shows the latest refusal", async () => {
    const user = userEvent.setup();
    render(<PlanLimitBanner />);
    refuse("First.");
    refuse("Second.");

    expect(screen.getByRole("status")).toHaveTextContent("Second.");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("isn't shown on the billing page itself", () => {
    navigation.pathname = "/settings/billing";
    render(<PlanLimitBanner />);

    refuse("Your plan allows 25 documents.");

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
