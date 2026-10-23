// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RevokeKeyState } from "@/lib/key-actions";

import { RevokeKeyButton } from "./revoke-key-button";

afterEach(cleanup);

function fakeAction(result: RevokeKeyState) {
  return vi.fn<
    (state: RevokeKeyState, form: FormData) => Promise<RevokeKeyState>
  >(async () => result);
}

function openConfirmation() {
  fireEvent.click(screen.getByRole("button", { name: "Revoke key gw_abcdef" }));
  return screen.getByRole("alertdialog", { name: "Revoke key gw_abcdef?" });
}

describe("RevokeKeyButton", () => {
  it("asks for confirmation before revoking, with the focus on Cancel", () => {
    const action = fakeAction({ status: "revoked", prefix: "gw_abcdef" });
    render(<RevokeKeyButton action={action} keyId={7} prefix="gw_abcdef" />);

    const dialog = openConfirmation();

    expect(dialog).toHaveTextContent("This cannot be undone.");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(action).not.toHaveBeenCalled();
  });

  it("revokes the key once confirmed", async () => {
    const action = fakeAction({ status: "revoked", prefix: "gw_abcdef" });
    render(<RevokeKeyButton action={action} keyId={7} prefix="gw_abcdef" />);

    openConfirmation();
    fireEvent.click(screen.getByRole("button", { name: "Revoke key" }));

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    expect(action.mock.calls[0][1].get("keyId")).toBe("7");
  });

  it("closes with Cancel without revoking, and gives the focus back", () => {
    const action = fakeAction({ status: "revoked", prefix: "gw_abcdef" });
    render(<RevokeKeyButton action={action} keyId={7} prefix="gw_abcdef" />);

    openConfirmation();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Revoke key gw_abcdef" }),
    ).toHaveFocus();
    expect(action).not.toHaveBeenCalled();
  });

  it("closes with the Escape key", () => {
    render(
      <RevokeKeyButton
        action={fakeAction({ status: "idle" })}
        keyId={7}
        prefix="gw_abcdef"
      />,
    );

    const dialog = openConfirmation();
    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows the error returned by the action, translated from its code", async () => {
    const action = fakeAction({
      status: "error",
      error: {
        kind: "api",
        status: 409,
        code: "key_already_revoked",
        message: "API key 7 is already revoked.",
      },
    });
    render(<RevokeKeyButton action={action} keyId={7} prefix="gw_abcdef" />);

    openConfirmation();
    fireEvent.click(screen.getByRole("button", { name: "Revoke key" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This API key is already revoked.",
    );
  });
});
