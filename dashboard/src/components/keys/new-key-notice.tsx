"use client";

import { useEffect, useRef, useState } from "react";

import type { CreatedKey } from "@/api/tenant-keys";
import { useTranslator } from "@/lib/i18n/client";

import { secondaryButtonClass } from "./form-feedback";

type CopyState = "idle" | "copied" | "failed";

/**
 * The full key just created, shown once.
 *
 * It lives only in the memory of this page: it is not written to the URL, the
 * session, a cookie or the browser storage. Leaving or refreshing the page loses it.
 */
export function NewKeyNotice({
  createdKey,
  onDismiss,
}: {
  createdKey: CreatedKey;
  onDismiss: () => void;
}) {
  const t = useTranslator();
  const [copy, setCopy] = useState<CopyState>("idle");
  const heading = useRef<HTMLHeadingElement>(null);

  // Move the focus to the notice, so keyboard and screen reader users find it.
  useEffect(() => heading.current?.focus(), []);

  async function copyKey() {
    try {
      // Missing outside a secure context (HTTPS or localhost), or refused.
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(createdKey.key);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  return (
    <section
      aria-labelledby="new-key-heading"
      className="flex flex-col gap-3 rounded border border-amber-300 bg-amber-50 p-4"
    >
      <h3
        id="new-key-heading"
        ref={heading}
        tabIndex={-1}
        className="font-semibold focus:outline-none"
      >
        {t("keys.newKey.heading", { tenant: createdKey.tenant })}
      </h3>
      <p className="text-sm font-medium text-amber-900">
        {t("keys.newKey.warning")}
      </p>
      <code
        aria-label={t("keys.newKey.label")}
        className="block rounded border border-amber-200 bg-white px-3 py-2 font-mono text-sm break-all select-all"
      >
        {createdKey.key}
      </code>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={copyKey}
          className={secondaryButtonClass}
        >
          {t("keys.newKey.copy")}
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className={secondaryButtonClass}
        >
          {t("keys.newKey.stored")}
        </button>
        <span role="status" className="text-sm">
          {copy === "copied" && t("keys.newKey.copied")}
        </span>
      </div>
      {copy === "failed" && (
        <p role="alert" className="text-sm text-red-800">
          {t("keys.newKey.copyFailed")}
        </p>
      )}
    </section>
  );
}
