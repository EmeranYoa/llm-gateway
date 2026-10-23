import { en } from "@/messages/en";
import { fr } from "@/messages/fr";
import type { MessageTree, PluralMessage } from "@/messages/types";

import { INTL_LOCALES, type Locale } from "./locale";

/**
 * `t()`: the text of a message in a language, with its placeholders filled.
 *
 *   const t = getTranslator("fr");
 *   t("nav.overview");                        // "Vue d’ensemble"
 *   t("apiError.englishDetail", { detail });  // "Détail (en anglais) : …"
 *   t("some.plural", { count: 1250 });        // "1 250 requêtes"
 *
 * Keys are the dotted paths of `messages/en.ts`, checked by the compiler, and
 * so are the values: a message with `{detail}` needs `{ detail }`, a plural
 * message needs `{ count }`. Numbers are written in the format of the language.
 *
 * Works the same in server and client components: it is a plain function.
 * Server pages get one with `getI18n()` (`./server`), client components with
 * `useTranslator()` (`./client`).
 */

/** Dotted paths to every message of `T`: `"nav.overview"`, `"apiError.codes.key_not_found"`. */
export type MessageKey<T> = {
  [K in keyof T & string]: T[K] extends string | PluralMessage
    ? K
    : `${K}.${MessageKey<T[K]>}`;
}[keyof T & string];

/** The message of `T` at the dotted path `K`. */
export type MessageAt<
  T,
  K extends string,
> = K extends `${infer Head}.${infer Rest}`
  ? Head extends keyof T
    ? MessageAt<T[Head], Rest>
    : never
  : K extends keyof T
    ? T[K]
    : never;

/** The names of the `{placeholders}` of a text: `"{used} / {limit}"` gives `"used" | "limit"`. */
export type Placeholders<S> = S extends `${string}{${infer Name}}${infer Rest}`
  ? Name | Placeholders<Rest>
  : never;

type Value = string | number;

/** What `t()` needs after the key: nothing, or an object with every placeholder. */
type ValuesArgument<M> = M extends PluralMessage
  ? [values: { count: number } & Record<Placeholders<M[keyof M]>, Value>]
  : [Placeholders<M>] extends [never]
    ? []
    : [values: Record<Placeholders<M>, Value>];

export type Translator<T = typeof en> = <K extends MessageKey<T>>(
  key: K,
  ...values: ValuesArgument<MessageAt<T, K>>
) => string;

/**
 * A translator for any dictionary. `T` is the reference dictionary that gives
 * the keys and placeholders (`typeof en` for the dashboard); `messages` holds
 * the texts of `locale`. A missing key shows the key itself.
 */
export function createTranslator<T extends MessageTree>(
  locale: Locale,
  messages: MessageTree,
): Translator<T> {
  const intlLocale = INTL_LOCALES[locale];
  const plurals = new Intl.PluralRules(intlLocale);
  const numbers = new Intl.NumberFormat(intlLocale);

  return ((key: string, values: Record<string, Value> = {}) => {
    const message = lookUp(messages, key);
    if (message === undefined) {
      return key;
    }
    const text =
      typeof message === "string"
        ? message
        : (message[plurals.select(Number(values.count))] ?? message.other);
    return text.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
      const value = values[name];
      if (value === undefined) {
        return placeholder;
      }
      return typeof value === "number" ? numbers.format(value) : value;
    });
  }) as Translator<T>;
}

function lookUp(
  messages: MessageTree,
  key: string,
): string | PluralMessage | undefined {
  let node: MessageTree[string] | undefined = messages;
  for (const part of key.split(".")) {
    if (node === undefined || typeof node === "string") {
      return undefined;
    }
    node = (node as MessageTree)[part];
  }
  if (typeof node === "string" || typeof node?.other === "string") {
    return node as string | PluralMessage;
  }
  return undefined;
}

const TRANSLATORS: Record<Locale, Translator> = {
  en: createTranslator<typeof en>("en", en),
  fr: createTranslator<typeof en>("fr", fr),
};

/** The translator of the dashboard's dictionaries for a language. */
export function getTranslator(locale: Locale): Translator {
  return TRANSLATORS[locale];
}
