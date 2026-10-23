"use client";

import { useState, useTransition } from "react";

import type { AdminAction, AdminActionPage } from "@/api/tenant-keys";
import { LocalDateTime } from "@/components/local-time";
import { useLocale } from "@/lib/i18n/client";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";
import type { LoadActionsResult } from "@/lib/key-actions";
import type { KeyFormError } from "@/lib/key-forms";
import { en } from "@/messages/en";

import { ErrorMessage, secondaryButtonClass } from "./form-feedback";

type ActionHistoryProps = {
  /** The newest actions, loaded with the page. */
  firstPage: AdminActionPage;
  /** The `loadActionsAction` server action. A prop, so tests can pass a fake one. */
  loadMore: (before: number) => Promise<LoadActionsResult>;
};

type DetailName = keyof typeof en.keys.history.detailNames;

/** The name of a detail in the language of the page; an unknown one is shown with spaces. */
function detailName(locale: Locale, name: string): string {
  if (!Object.hasOwn(en.keys.history.detailNames, name)) {
    return name.replaceAll("_", " ");
  }
  return getTranslator(locale)(
    `keys.history.detailNames.${name as DetailName}`,
  );
}

/** One line from the details of an action, e.g. "prefix gw_abc, rpm 30". */
export function summarizeDetails(action: AdminAction, locale: Locale): string {
  const t = getTranslator(locale);
  const parts = Object.entries(action.details).map(([name, value]) => {
    if (value === null && name === "alias") {
      return t("keys.history.everyAlias");
    }
    const text =
      typeof value === "object" && value !== null
        ? JSON.stringify(value)
        : String(value);
    return `${detailName(locale, name)} ${text}`;
  });
  return parts.length === 0 ? "-" : parts.join(", ");
}

/** What the action changed: a tenant name, a key id, or every tenant. */
function describeTarget(action: AdminAction, locale: Locale): string {
  const t = getTranslator(locale);
  if (action.target === null) {
    return t("keys.history.everyTenant");
  }
  return KEY_ID_TARGETS.has(action.action)
    ? t("keys.history.key", { id: action.target })
    : action.target;
}

/** The action in the language of the page; one added after this dashboard keeps its id. */
function actionName(action: AdminAction, locale: Locale): string {
  if (!Object.hasOwn(en.keys.history.actions, action.action)) {
    return action.action;
  }
  return getTranslator(locale)(`keys.history.actions.${action.action}`);
}

/** Actions whose target is the id of a key; the others target a tenant. */
const KEY_ID_TARGETS = new Set<AdminAction["action"]>([
  "revoke-key",
  "create-admin-key",
  "revoke-admin-key",
]);

/** History of admin actions, newest first, with older pages loaded on demand. */
export function ActionHistory({ firstPage, loadMore }: ActionHistoryProps) {
  const locale = useLocale();
  const t = getTranslator(locale);
  const [actions, setActions] = useState(firstPage.actions);
  const [nextBefore, setNextBefore] = useState(firstPage.next_before);
  const [error, setError] = useState<KeyFormError | null>(null);
  const [pending, startTransition] = useTransition();

  function loadOlder() {
    if (nextBefore === null) {
      return;
    }
    startTransition(async () => {
      const result = await loadMore(nextBefore);
      if (result.status === "error") {
        setError(result.error);
        return;
      }
      setError(null);
      setActions((shown) => [...shown, ...result.page.actions]);
      setNextBefore(result.page.next_before);
    });
  }

  if (actions.length === 0) {
    return <p className="text-sm text-slate-600">{t("keys.history.empty")}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
            <tr>
              <th scope="col" className="px-3 py-2">
                {t("keys.history.time")}
              </th>
              <th scope="col" className="px-3 py-2">
                {t("keys.history.actor")}
              </th>
              <th scope="col" className="px-3 py-2">
                {t("keys.history.action")}
              </th>
              <th scope="col" className="px-3 py-2">
                {t("keys.history.target")}
              </th>
              <th scope="col" className="px-3 py-2">
                {t("keys.history.details")}
              </th>
            </tr>
          </thead>
          <tbody>
            {actions.map((action) => (
              <tr key={action.id} className="border-t border-slate-100">
                <td className="px-3 py-2 whitespace-nowrap">
                  <LocalDateTime iso={action.created_at} />
                </td>
                <td className="px-3 py-2">{action.actor}</td>
                <td className="px-3 py-2" title={action.action}>
                  {actionName(action, locale)}
                </td>
                <td className="px-3 py-2">{describeTarget(action, locale)}</td>
                <td className="px-3 py-2 text-slate-600">
                  {summarizeDetails(action, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <ErrorMessage error={error} />}
      {nextBefore !== null && (
        <div>
          <button
            type="button"
            onClick={loadOlder}
            disabled={pending}
            className={secondaryButtonClass}
          >
            {pending ? t("keys.history.loading") : t("keys.history.loadMore")}
          </button>
        </div>
      )}
    </div>
  );
}
