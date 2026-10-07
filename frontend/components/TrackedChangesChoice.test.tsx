import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/services/api/client";

import { TrackedChangesChoice } from "./TrackedChangesChoice";

/** A Word file's tracked changes: kept for Word, all accepted or all rejected, as the person chooses (DOCX-022, DOCX-022A). */

const EDITS = new ApiError(409, { code: "edits_would_be_lost", message: "What you changed here would be replaced." }, "", null);

describe("the tracked changes choice", () => {
  it("shows what is chosen and makes a new choice", async () => {
    const onChoose = vi.fn().mockResolvedValue(undefined);
    render(<TrackedChangesChoice choice="kept" onChoose={onChoose} />);

    expect(screen.getByRole("radio", { name: /Keep them in the Word export/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /Accept them all/ }));

    await waitFor(() => expect(onChoose).toHaveBeenCalledWith("accepted"));
  });

  it("asks for nothing when the choice doesn't change", () => {
    const onChoose = vi.fn().mockResolvedValue(undefined);
    render(<TrackedChangesChoice choice="accepted" onChoose={onChoose} />);

    fireEvent.click(screen.getByRole("radio", { name: /Accept them all/ }));

    expect(onChoose).not.toHaveBeenCalled();
  });

  it("says so when the choice can't be made", async () => {
    render(<TrackedChangesChoice choice="kept" onChoose={vi.fn().mockRejectedValue(new Error("The server said no."))} />);

    fireEvent.click(screen.getByRole("radio", { name: /Accept them all/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server said no.");
  });

  it("asks first when rejecting them would replace changes made here, and goes on only if told to", async () => {
    const onChoose = vi.fn().mockRejectedValueOnce(EDITS).mockResolvedValueOnce(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<TrackedChangesChoice choice="kept" onChoose={onChoose} />);

    fireEvent.click(screen.getByRole("radio", { name: /Reject them all/ }));

    await waitFor(() => expect(onChoose).toHaveBeenLastCalledWith("rejected", true));
    expect(onChoose).toHaveBeenNthCalledWith(1, "rejected");
    expect(confirm).toHaveBeenCalledWith("What you changed here would be replaced.");
    confirm.mockRestore();
  });

  it("changes nothing when the person says no", async () => {
    const onChoose = vi.fn().mockRejectedValueOnce(EDITS);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<TrackedChangesChoice choice="kept" onChoose={onChoose} />);

    fireEvent.click(screen.getByRole("radio", { name: /Reject them all/ }));

    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
    confirm.mockRestore();
  });

  it("once rejected, says how to get them back instead of offering a choice", () => {
    render(<TrackedChangesChoice choice="rejected" onChoose={vi.fn()} />);

    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByText(/Undo brings them back/)).toBeInTheDocument();
  });
});
