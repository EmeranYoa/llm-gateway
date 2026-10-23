// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PeriodFilter, TenantFilter } from "./filters";

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
