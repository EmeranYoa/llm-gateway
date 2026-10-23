// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/client";
import type { CreateKeyState } from "@/lib/key-actions";

import { CreateKeyForm } from "./create-key-form";

const FULL_KEY = "gw_" + "s".repeat(43);
const CREATED: CreateKeyState = {
  status: "created",
  key: { id: 7, tenant: "acme", prefix: "gw_ssssss", key: FULL_KEY },
};

function fakeAction(result: CreateKeyState) {
  return vi.fn<
    (state: CreateKeyState, form: FormData) => Promise<CreateKeyState>
  >(async () => result);
}

function setClipboard(clipboard: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    value: clipboard,
    configurable: true,
  });
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: "Create key" }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  setClipboard(undefined);
});

describe("CreateKeyForm", () => {
  it("sends the tenant and the limits to the action", async () => {
    const action = fakeAction(CREATED);
    render(<CreateKeyForm action={action} tenants={["acme"]} />);

    fill("Tenant", "acme");
    fill("Requests per minute (optional)", "30");
    submit();

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
    const form = action.mock.calls[0][1];
    expect(form.get("tenant")).toBe("acme");
    expect(form.get("rpm")).toBe("30");
    expect(form.get("tokens_per_day")).toBe("");
  });

  it("fills in the selected tenant and suggests the known ones", () => {
    const { container } = render(
      <CreateKeyForm
        action={fakeAction(CREATED)}
        tenants={["acme", "beta"]}
        defaultTenant="beta"
      />,
    );

    expect(screen.getByLabelText("Tenant")).toHaveValue("beta");
    const options = container.querySelectorAll("datalist option");
    expect([...options].map((option) => option.getAttribute("value"))).toEqual([
      "acme",
      "beta",
    ]);
  });

  it("shows the new key once, with a warning and a copy button", async () => {
    render(<CreateKeyForm action={fakeAction(CREATED)} tenants={[]} />);

    fill("Tenant", "acme");
    submit();

    expect(await screen.findByLabelText("New API key")).toHaveTextContent(
      FULL_KEY,
    );
    expect(screen.getByText(/never be shown again/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy key" })).toBeEnabled();
  });

  it("copies the key with the Clipboard API", async () => {
    const writeText = vi.fn(async () => {});
    setClipboard({ writeText });
    render(<CreateKeyForm action={fakeAction(CREATED)} tenants={[]} />);
    fill("Tenant", "acme");
    submit();

    fireEvent.click(await screen.findByRole("button", { name: "Copy key" }));

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Copied to the clipboard.",
      ),
    );
    expect(writeText).toHaveBeenCalledWith(FULL_KEY);
  });

  it("explains how to copy by hand when the Clipboard API is missing", async () => {
    setClipboard(undefined);
    render(<CreateKeyForm action={fakeAction(CREATED)} tenants={[]} />);
    fill("Tenant", "acme");
    submit();

    fireEvent.click(await screen.findByRole("button", { name: "Copy key" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /copy it by hand/,
    );
    expect(screen.getByLabelText("New API key")).toHaveTextContent(FULL_KEY);
  });

  it("explains how to copy by hand when the browser refuses to copy", async () => {
    setClipboard({
      writeText: vi.fn(async () => {
        throw new DOMException("Denied", "NotAllowedError");
      }),
    });
    render(<CreateKeyForm action={fakeAction(CREATED)} tenants={[]} />);
    fill("Tenant", "acme");
    submit();

    fireEvent.click(await screen.findByRole("button", { name: "Copy key" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /copy it by hand/,
    );
  });

  it("never writes the key to the browser storage, a cookie or the URL", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const urlBefore = window.location.href;
    setClipboard({ writeText: vi.fn(async () => {}) });
    render(<CreateKeyForm action={fakeAction(CREATED)} tenants={[]} />);
    fill("Tenant", "acme");
    submit();
    fireEvent.click(await screen.findByRole("button", { name: "Copy key" }));
    await screen.findByText("Copied to the clipboard.");

    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain(FULL_KEY);
    expect(window.location.href).toBe(urlBefore);
    expect(window.location.href).not.toContain(FULL_KEY);
  });

  it("hides the key for good once the operator has stored it", async () => {
    render(<CreateKeyForm action={fakeAction(CREATED)} tenants={[]} />);
    fill("Tenant", "acme");
    submit();

    fireEvent.click(
      await screen.findByRole("button", { name: "I have stored the key" }),
    );

    expect(screen.queryByText(FULL_KEY)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain(FULL_KEY);
  });

  it("refuses a bad limit without calling the action", async () => {
    const action = fakeAction(CREATED);
    render(<CreateKeyForm action={action} tenants={[]} />);

    fill("Tenant", "acme");
    fill("Tokens per day (optional)", "0");
    submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Tokens per day must be a whole number greater than 0.",
    );
    expect(action).not.toHaveBeenCalled();
  });

  it("shows the error returned by the action, and keeps the values typed", async () => {
    const action = fakeAction({
      status: "error",
      error: {
        kind: "api",
        status: 400,
        code: null,
        message: "Invalid value for 'rpm'.",
      },
    });
    render(<CreateKeyForm action={action} tenants={[]} />);

    fill("Tenant", "acme");
    fill("Requests per minute (optional)", "99999999999");
    submit();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The admin API refused the values.");
    expect(alert).toHaveTextContent("Invalid value for 'rpm'.");
    expect(screen.getByLabelText("Tenant")).toHaveValue("acme");
  });

  it("speaks French, checks of the form included", async () => {
    const action = fakeAction(CREATED);
    render(
      <LocaleProvider locale="fr">
        <CreateKeyForm action={action} tenants={[]} />
      </LocaleProvider>,
    );

    fireEvent.change(screen.getByLabelText("Tenant"), {
      target: { value: "acme" },
    });
    fireEvent.change(screen.getByLabelText("Tokens par jour (facultatif)"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Créer la clé" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Tokens par jour : saisissez un nombre entier supérieur à 0.",
    );
    expect(action).not.toHaveBeenCalled();
  });
});
