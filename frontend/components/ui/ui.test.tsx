import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./Button";
import { Notice } from "./Notice";
import { TextField } from "./TextField";

describe("Button (SmartDoc 2.0 primitives)", () => {
  it("is a plain button by default and calls back when pressed", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Create project</Button>);

    const button = screen.getByRole("button", { name: "Create project" });
    expect(button).toHaveAttribute("type", "button");  // never submits a form by accident
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("while loading: says what it is doing, is busy and can't be pressed again", () => {
    const onClick = vi.fn();
    render(
      <Button loading loadingLabel="Signing in…" onClick={onClick}>
        Sign in
      </Button>,
    );

    const button = screen.getByRole("button", { name: "Signing in…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("TextField", () => {
  it("is found by its label, with the hint tied to it", () => {
    render(<TextField label="Password" type="password" hint="At least 8 characters." />);

    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAccessibleDescription("At least 8 characters.");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("marks an error for assistive technology", () => {
    render(<TextField label="Email" error="Enter a valid email address." />);

    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a valid email address.");
  });

  it("keeps two fields' ids apart", () => {
    render(
      <>
        <TextField label="First" />
        <TextField label="Second" />
      </>,
    );
    expect(screen.getByLabelText("First").id).not.toBe(screen.getByLabelText("Second").id);
  });
});

describe("Notice", () => {
  it("announces an error at once and other notices politely", () => {
    render(
      <>
        <Notice tone="error">Invalid email or password.</Notice>
        <Notice tone="success">Saved.</Notice>
      </>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(screen.getByRole("status")).toHaveTextContent("Saved.");
  });
});
