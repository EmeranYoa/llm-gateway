// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { richText } from "./rich-text";
import { getTranslator } from "./translator";

afterEach(cleanup);

describe("richText", () => {
  it("puts elements where the language puts the placeholders", () => {
    const nodes = {
      start: <time dateTime="2026-10-22">22 oct.</time>,
      end: <time dateTime="2026-10-23">23 oct.</time>,
    };

    const { container } = render(
      <p>{richText(getTranslator("fr"), "time.range", nodes)}</p>,
    );

    expect(container.textContent).toBe("Du 22 oct. au 23 oct.");
    expect(container.querySelectorAll("time")).toHaveLength(2);
  });

  it("keeps the text around one element", () => {
    const { container } = render(
      <p>
        {richText(getTranslator("en"), "tenants.empty", {
          command: <code>python -m app.admin</code>,
        })}
      </p>,
    );

    expect(container.textContent).toBe(
      "No tenant yet. Create one with python -m app.admin.",
    );
    expect(container.querySelector("code")).toHaveTextContent(
      "python -m app.admin",
    );
  });
});
