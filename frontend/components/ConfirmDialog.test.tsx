import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("starts on Cancel, so Enter never confirms by accident", () => {
    render(
      <ConfirmDialog title="Delete this document?" confirmLabel="Delete" onConfirm={vi.fn()} onCancel={vi.fn()}>
        It can&apos;t be undone.
      </ConfirmDialog>,
    );

    expect(screen.getByRole("alertdialog", { name: "Delete this document?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("confirms, cancels, and cancels on Escape", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog title="Delete?" confirmLabel="Delete" onConfirm={onConfirm} onCancel={onCancel}>
        Gone for good.
      </ConfirmDialog>,
    );

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.keyboard("{Escape}");

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("can't be dismissed while the action runs, and shows what went wrong", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog title="Delete?" confirmLabel="Delete" busy error="The document couldn't be deleted." onConfirm={vi.fn()} onCancel={onCancel}>
        Gone for good.
      </ConfirmDialog>,
    );

    await user.keyboard("{Escape}");

    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Delete/ })).toBeDisabled();
    expect(screen.getByText("The document couldn't be deleted.")).toBeInTheDocument();
  });
});
