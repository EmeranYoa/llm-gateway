import type { en } from "./en";

/**
 * Shapes of the dictionaries of the dashboard.
 *
 * `en.ts` is the reference. Every other language is typed `Messages`, built
 * from `en.ts`: the compiler fails when a translation misses a key of `en.ts`
 * or has a key that `en.ts` does not have.
 */

/**
 * A message that depends on a number, chosen with `Intl.PluralRules`:
 * `{ one: "{count} request", other: "{count} requests" }`. `other` is required;
 * a language adds the categories it needs (`zero`, `two`, `few`, `many`).
 *
 * A key named `other` marks a plural message: never use it as a message name.
 */
export type PluralMessage = { readonly other: string } & {
  readonly [category in Intl.LDMLPluralRule]?: string;
};

/** A dictionary: messages, plural messages, and groups of them. */
export type MessageTree = {
  readonly [key: string]: string | PluralMessage | MessageTree;
};

/** The shape of `T` with any text in its messages: what a translation must fill. */
export type Translation<T> = T extends string
  ? string
  : T extends PluralMessage
    ? PluralMessage
    : { readonly [K in keyof T]: Translation<T[K]> };

/** The type of every dictionary: the keys of `en.ts`, any text. */
export type Messages = Translation<typeof en>;
