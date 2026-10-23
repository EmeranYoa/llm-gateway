// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CacheClearState } from "@/lib/key-actions";

import { CacheClearForm } from "./cache-clear-form";

afterEach(cleanup);

function fakeAction(result: CacheClearState) {
  return vi.fn<
    (state: CacheClearState, form: FormData) => Promise<CacheClearState>
  >(async () => result);
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Clear cache" }));
}

describe("CacheClearForm", () => {
  it("shows how many answers were removed for every alias", async () => {
    const action = fakeAction({
      status: "cleared",
      removed: 3,
      tenant: "acme",
      alias: null,
    });
    render(<CacheClearForm action={action} tenant="acme" />);

    submit();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Removed 3 cached answers (every alias).",
    );
    const form = action.mock.calls[0][1];
    expect(form.get("tenant")).toBe("acme");
    expect(form.get("alias")).toBe("");
  });

  it("clears one alias when one is given", async () => {
    const action = fakeAction({
      status: "cleared",
      removed: 1,
      tenant: "acme",
      alias: "chat-fast",
    });
    render(<CacheClearForm action={action} tenant="acme" />);

    fireEvent.change(screen.getByLabelText(/Alias/), {
      target: { value: "chat-fast" },
    });
    submit();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Removed 1 cached answer (alias chat-fast).",
    );
    expect(action.mock.calls[0][1].get("alias")).toBe("chat-fast");
  });

  it("shows the error returned by the action", async () => {
    render(
      <CacheClearForm
        action={fakeAction({
          status: "error",
          error: {
            kind: "api",
            status: 503,
            code: "redis_unavailable",
            message: "Redis is unavailable. Try again later.",
          },
        })}
        tenant="acme"
      />,
    );

    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Redis is unavailable. Try again later.",
    );
  });
});
