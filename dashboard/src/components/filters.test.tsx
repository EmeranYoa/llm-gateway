// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AliasFilter,
  PeriodFilter,
  RequestStatusFilter,
  TenantFilter,
} from "./filters";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
  search: "",
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

beforeEach(() => {
  navigation.push.mockReset();
  navigation.search = "";
});

afterEach(cleanup);

describe("PeriodFilter", () => {
  it("shows the current period", () => {
    render(<PeriodFilter value="7d" />);

    expect(screen.getByLabelText("Period")).toHaveValue("7d");
  });

  it("writes the period to the URL and keeps the other filters", () => {
    navigation.search = "period=24h&tenant=acme";
    render(<PeriodFilter value="24h" />);

    fireEvent.change(screen.getByLabelText("Period"), {
      target: { value: "30d" },
    });

    expect(navigation.push).toHaveBeenCalledWith("/?period=30d&tenant=acme", {
      scroll: false,
    });
  });
});

describe("filters of a paged list", () => {
  it("go back to the first page when a filter changes", () => {
    navigation.search = "period=24h&tenant=acme&cursor=abc";
    render(<PeriodFilter value="24h" />);

    fireEvent.change(screen.getByLabelText("Period"), {
      target: { value: "7d" },
    });

    expect(navigation.push).toHaveBeenCalledWith("/?period=7d&tenant=acme", {
      scroll: false,
    });
  });
});

describe("RequestStatusFilter", () => {
  it("offers every status, and all of them", () => {
    render(<RequestStatusFilter value="failed" />);

    expect(screen.getByLabelText("Status")).toHaveValue("failed");
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual([
      "All statuses",
      "Answered",
      "Failed",
      "Client error",
      "Cancelled",
    ]);
  });

  it("writes the status to the URL, or removes it for all", () => {
    navigation.search = "period=7d&status=failed";
    render(<RequestStatusFilter value="failed" />);

    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "client_error" },
    });
    expect(navigation.push).toHaveBeenLastCalledWith(
      "/?period=7d&status=client_error",
      { scroll: false },
    );

    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "" },
    });
    expect(navigation.push).toHaveBeenLastCalledWith("/?period=7d", {
      scroll: false,
    });
  });
});

describe("AliasFilter", () => {
  it("writes the typed alias to the URL when applied", () => {
    navigation.search = "period=7d&cursor=abc";
    render(<AliasFilter value={null} suggestions={["chat-fast"]} />);

    fireEvent.change(screen.getByLabelText("Alias"), {
      target: { value: " chat-smart " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(navigation.push).toHaveBeenCalledWith(
      "/?period=7d&alias=chat-smart",
      { scroll: false },
    );
  });

  it("removes the alias from the URL when the field is emptied", () => {
    navigation.search = "period=7d&alias=chat-fast";
    render(<AliasFilter value="chat-fast" suggestions={[]} />);

    expect(screen.getByLabelText("Alias")).toHaveValue("chat-fast");
    fireEvent.change(screen.getByLabelText("Alias"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(navigation.push).toHaveBeenCalledWith("/?period=7d", {
      scroll: false,
    });
  });
});

describe("TenantFilter", () => {
  it("offers every tenant, and all of them", () => {
    render(<TenantFilter value={null} tenants={["zeta", "acme"]} />);

    const select = screen.getByLabelText("Tenant");
    expect(select).toHaveValue("");
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["All tenants", "acme", "zeta"]);
  });

  it("writes the tenant to the URL", () => {
    navigation.search = "period=7d";
    render(<TenantFilter value={null} tenants={["acme"]} />);

    fireEvent.change(screen.getByLabelText("Tenant"), {
      target: { value: "acme" },
    });

    expect(navigation.push).toHaveBeenCalledWith("/?period=7d&tenant=acme", {
      scroll: false,
    });
  });

  it("removes the tenant from the URL for all tenants", () => {
    navigation.search = "period=7d&tenant=acme";
    render(<TenantFilter value="acme" tenants={["acme"]} />);

    fireEvent.change(screen.getByLabelText("Tenant"), {
      target: { value: "" },
    });

    expect(navigation.push).toHaveBeenCalledWith("/?period=7d", {
      scroll: false,
    });
  });

  it("keeps offering a selected tenant missing from the list", () => {
    render(<TenantFilter value="gone" tenants={["acme"]} />);

    expect(screen.getByLabelText("Tenant")).toHaveValue("gone");
  });
});
