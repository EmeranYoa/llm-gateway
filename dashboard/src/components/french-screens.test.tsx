// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LocaleProvider } from "@/lib/i18n/client";
import {
  liveFixture,
  overviewFixture,
  routingStepFixture,
  targetFixture,
} from "@/test/fixtures";

import { OverviewFigures } from "./overview-figures";
import { TargetHealthBadges } from "./providers/target-card";
import { RequestsPagination } from "./requests/pagination";
import { RoutingPath } from "./requests/routing-path";

/**
 * The screens in French. Their tests render in English (the default); these
 * prove the French path: texts, plurals and number formats.
 * (`toHaveTextContent` and `getByText` read no-break spaces as plain spaces.)
 */

afterEach(cleanup);

describe("screens in French", () => {
  it("shows the overview figures, with French plurals and numbers", () => {
    render(<OverviewFigures overview={overviewFixture()} locale="fr" />);

    const heading = screen.getByRole("heading", { name: "Taux d’erreur" });
    const card = heading.closest("div.rounded-lg") as HTMLElement;
    expect(card).toHaveTextContent(
      "25 en échec. Non comptées : 20 erreurs client, 5 annulées.",
    );
    expect(
      // `\s` also matches the no-break space before the colon.
      screen.getByRole("button", { name: /^Définition\s:\sTaux d’erreur$/ }),
    ).toHaveAccessibleDescription(/Requêtes échouées \/ requêtes/);
    expect(screen.getByText("1 200 servies")).toBeInTheDocument();
    expect(screen.getByText("1,50 $")).toBeInTheDocument();
  });

  it("names the status of a target, with its definition", () => {
    const target = targetFixture({
      live: liveFixture({
        cooldown: { active: true, until: "2026-10-23T12:01:00Z" },
      }),
    });

    render(<TargetHealthBadges target={target} locale="fr" />);

    const badge = within(screen.getByRole("list", { name: "État" })).getByText(
      "En pause",
    );
    expect(badge).toHaveAttribute(
      "title",
      expect.stringContaining("la cible est ignorée"),
    );
  });

  it("names the outcomes of a routing path", () => {
    render(
      <RoutingPath
        steps={[
          routingStepFixture({
            attempt_index: 0,
            outcome: "rate_limited",
            status_code: 429,
          }),
          routingStepFixture({ attempt_index: 1 }),
        ]}
        locale="fr"
      />,
    );

    const first = screen.getByRole("listitem", { name: "Étape 1" });
    expect(first).toHaveTextContent("Erreur");
    expect(first).toHaveTextContent("Limite de débit (429)");
    const second = screen.getByRole("listitem", { name: "Étape 2" });
    expect(second).toHaveTextContent("Réussite");
    expect(second).toHaveTextContent("Servie");
    expect(second).toHaveTextContent("120 prompt · 80 réponse · 600 estimés");
  });

  it("translates the links of the pages of requests", () => {
    render(
      <LocaleProvider locale="fr">
        <RequestsPagination
          filters={{ period: "24h", tenant: null, alias: null, status: null }}
          cursor="abc"
          nextCursor="def"
          locale="fr"
        />
      </LocaleProvider>,
    );

    expect(
      screen.getByRole("navigation", { name: "Pages de requêtes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Requêtes plus anciennes" }),
    ).toBeInTheDocument();
  });
});
