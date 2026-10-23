// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LimitsState } from "@/lib/key-actions";

import { LimitsForm } from "./limits-form";

afterEach(cleanup);

function fakeAction(result: LimitsState) {
  return vi.fn<(state: LimitsState, form: FormData) => Promise<LimitsState>>(
    async () => result,
  );
}

function renderForm(action: ReturnType<typeof fakeAction>) {
  render(
    <LimitsForm
      action={action}
      tenant="acme"
      effectiveLimits={{ rpm: 60, tokens_per_day: null }}
    />,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Save limits" }));
}

describe("LimitsForm", () => {
  it("shows the limits applied now as hints", () => {
    renderForm(fakeAction({ status: "saved" }));

    expect(screen.getByLabelText("Requests per minute")).toHaveAttribute(
      "placeholder",
      "now: 60",
    );
    expect(screen.getByLabelText("Tokens per day")).toHaveAttribute(
      "placeholder",
      "now: no limit",
    );
  });

  it("asks for at least one limit", async () => {
    const action = fakeAction({ status: "saved" });
    renderForm(action);

    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Give at least one limit",
    );
    expect(action).not.toHaveBeenCalled();
  });

  it.each(["0", "-5", "1.5"])(
    "refuses %s, which is not a positive whole number",
    async (value) => {
      const action = fakeAction({ status: "saved" });
      renderForm(action);

      fill("Requests per minute", value);
      submit();

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Requests per minute must be a whole number greater than 0.",
      );
      expect(action).not.toHaveBeenCalled();
    },
  );

  it("sends the tenant and the limits, then confirms", async () => {
    const action = fakeAction({ status: "saved" });
    renderForm(action);

    fill("Tokens per day", "50000");
    submit();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Limits saved.",
    );
    const form = action.mock.calls[0][1];
    expect(form.get("tenant")).toBe("acme");
    expect(form.get("tokens_per_day")).toBe("50000");
    expect(form.get("rpm")).toBe("");
  });

  it("shows the validation error of the admin API", async () => {
    const action = fakeAction({
      status: "error",
      error: {
        kind: "api",
        status: 400,
        code: null,
        message:
          "Invalid value for 'rpm': Input should be less than or equal to 2147483647",
      },
    });
    renderForm(action);

    fill("Requests per minute", "3000000000");
    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Input should be less than or equal to 2147483647",
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Requests per minute")).toHaveValue(
        3000000000,
      ),
    );
  });
});
