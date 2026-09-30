import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TrackedChangesChoice } from "./TrackedChangesChoice";

/** A Word file's tracked changes: kept for Word or all accepted, as the person chooses (DOCX-022). */

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
});
