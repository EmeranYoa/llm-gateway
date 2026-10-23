import { Fragment, type ReactNode } from "react";

import type { en } from "@/messages/en";

import type {
  MessageAt,
  MessageKey,
  Placeholders,
  Translator,
} from "./translator";

type Key = MessageKey<typeof en>;

/**
 * A message whose placeholders are React elements instead of text: a `<time>`,
 * a `<code>` or a link inside a sentence, wherever the language puts it.
 *
 *   richText(t, "providers.cooldownUntil", {
 *     time: <LocalDateTime iso={until} seconds />,
 *   });
 *
 * The keys and placeholder names are checked by the compiler, as with `t()`.
 */
export function richText<K extends Key>(
  t: Translator,
  key: K,
  nodes: Record<Placeholders<MessageAt<typeof en, K>>, ReactNode>,
): ReactNode {
  const elements: Record<string, ReactNode> = nodes;
  // Ask `t()` to keep each placeholder as it is, then put the elements there.
  const kept = Object.fromEntries(
    Object.keys(elements).map((name) => [name, `{${name}}`]),
  );
  const text = (t as (key: string, values: Record<string, string>) => string)(
    key,
    kept,
  );
  return text.split(/(\{\w+\})/).map((part, index) => {
    const name = /^\{(\w+)\}$/.exec(part)?.[1];
    return (
      <Fragment key={index}>
        {name !== undefined && Object.hasOwn(elements, name)
          ? elements[name]
          : part}
      </Fragment>
    );
  });
}
