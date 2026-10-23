// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatCard } from "./stat-card";

afterEach(cleanup);

describe("StatCard", () => {
  it("renders the label, the value and the definition as a tooltip", () => {
    render(
      <StatCard
        label="Error rate"
        value="2.5%"
        definition="failed / requests."
      />,
    );

    expect(screen.getByRole("heading", { name: "Error rate" })).toBeVisible();
    expect(screen.getByText("2.5%")).toBeInTheDocument();
    const button = screen.getByRole("button", {
      name: "Definition of Error rate",
    });
    expect(button).toHaveAccessibleDescription("failed / requests.");
    expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent(
      "failed / requests.",
    );
  });

  it("renders a detail and a warning when given", () => {
    render(
      <StatCard
        label="Cost"
        value="$1.20"
        definition="Cost of every attempt that has a price."
        detail="Saved by the cache: $0.40"
        warning="3 requests without a price"
      />,
    );

    expect(screen.getByText("Saved by the cache: $0.40")).toBeInTheDocument();
    expect(screen.getByText(/3 requests without a price/)).toBeInTheDocument();
  });
});
