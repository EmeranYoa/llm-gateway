import { describe, expect, it } from "vitest";

import { en } from "./en";
import { fr } from "./fr";
import type { Messages } from "./types";

/**
 * The compiler checks that `fr.ts` has exactly the keys of `en.ts` (`bun run
 * typecheck`): each `@ts-expect-error` below fails the build if the mistake
 * under it stops being an error. The runtime tests check the same contract on
 * the real dictionaries, plus their placeholders.
 */

// @ts-expect-error: a translation that misses a key of en.ts does not compile.
const missingKey: Messages = { ...fr, language: {} };

const extraKey: Messages = {
  ...fr,
  // @ts-expect-error: a key that en.ts does not have does not compile.
  language: { label: "Langue", region: "Région" },
};

const notText: Messages = {
  ...fr,
  // @ts-expect-error: a message is text, not a group.
  language: { label: { short: "Langue" } },
};

type Tree = { [key: string]: string | Tree };

/** Every message of a dictionary, by dotted key. */
function flatten(tree: Tree, prefix = ""): Map<string, string> {
  const flat = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = `${prefix}${key}`;
    if (typeof value === "string") {
      flat.set(path, value);
    } else if (typeof value.other === "string") {
      // A plural message: every variant counts, under the key of the message.
      flat.set(path, Object.values(value).join(" "));
    } else {
      for (const [inner, text] of flatten(value, `${path}.`)) {
        flat.set(inner, text);
      }
    }
  }
  return flat;
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
}

describe("dictionaries", () => {
  it("keeps the compile-time examples (they are types only)", () => {
    expect([missingKey, extraKey, notText]).toHaveLength(3);
  });

  it("have the same keys in English and in French", () => {
    const english = flatten(en as unknown as Tree);
    const french = flatten(fr as unknown as Tree);

    expect([...french.keys()].sort()).toEqual([...english.keys()].sort());
  });

  it("use the same placeholders in English and in French", () => {
    const english = flatten(en as unknown as Tree);
    const french = flatten(fr as unknown as Tree);

    for (const [key, text] of english) {
      expect([...new Set(placeholders(french.get(key) ?? ""))], key).toEqual([
        ...new Set(placeholders(text)),
      ]);
    }
  });

  it("never translate a message with an empty text", () => {
    for (const [key, text] of flatten(fr as unknown as Tree)) {
      expect(text.trim(), key).not.toBe("");
    }
  });
});
