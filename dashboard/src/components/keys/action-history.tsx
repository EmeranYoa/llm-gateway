"use client";

import { useState, useTransition } from "react";

import type { AdminAction, AdminActionPage } from "@/api/tenant-keys";
import type { LoadActionsResult } from "@/lib/key-actions";

import { ErrorMessage, secondaryButtonClass } from "./form-feedback";
import { LocalTime } from "./local-time";

type ActionHistoryProps = {
  /** The newest actions, loaded with the page. */
  firstPage: AdminActionPage;
  /** The `loadActionsAction` server action. A prop, so tests can pass a fake one. */
  loadMore: (before: number) => Promise<LoadActionsResult>;
};

const DETAIL_LABELS: Record<string, string> = {
  key_id: "key id",
  tokens_per_day: "tokens per day",
};

/** One line from the details of an action, e.g. "prefix gw_abc, rpm 30". */
export function summarizeDetails(action: AdminAction): string {
  const parts = Object.entries(action.details).map(([name, value]) => {
    const label = DETAIL_LABELS[name] ?? name.replaceAll("_", " ");
    if (value === null && name === "alias") {
      return "every alias";
    }
    const text =
      typeof value === "object" && value !== null
        ? JSON.stringify(value)
        : String(value);
    return `${label} ${text}`;
  });
  return parts.length === 0 ? "-" : parts.join(", ");
}

/** What the action changed: a tenant name, a key id, or every tenant. */
function describeTarget(action: AdminAction): string {
  if (action.target === null) {
    return "every tenant";
  }
  return KEY_ID_TARGETS.has(action.action)
    ? `key ${action.target}`
    : action.target;
}

/** Actions whose target is the id of a key; the others target a tenant. */
const KEY_ID_TARGETS = new Set<AdminAction["action"]>([
  "revoke-key",
  "create-admin-key",
  "revoke-admin-key",
]);

/** History of admin actions, newest first, with older pages loaded on demand. */
export function ActionHistory({ firstPage, loadMore }: ActionHistoryProps) {
  const [actions, setActions] = useState(firstPage.actions);
  const [nextBefore, setNextBefore] = useState(firstPage.next_before);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function loadOlder() {
    if (nextBefore === null) {
      return;
    }
    startTransition(async () => {
      const result = await loadMore(nextBefore);
      if (result.status === "error") {
        setError(result.message);
        return;
      }
      setError(null);
      setActions((shown) => [...shown, ...result.page.actions]);
      setNextBefore(result.page.next_before);
    });
  }

  if (actions.length === 0) {
    return <p className="text-sm text-slate-600">No admin action yet.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
            <tr>
              <th scope="col" className="px-3 py-2">
                Time
              </th>
              <th scope="col" className="px-3 py-2">
                Actor
              </th>
              <th scope="col" className="px-3 py-2">
                Action
              </th>
              <th scope="col" className="px-3 py-2">
                Target
              </th>
              <th scope="col" className="px-3 py-2">
                Details
              </th>
            </tr>
          </thead>
          <tbody>
            {actions.map((action) => (
              <tr key={action.id} className="border-t border-slate-100">
                <td className="px-3 py-2 whitespace-nowrap">
                  <LocalTime value={action.created_at} />
                </td>
                <td className="px-3 py-2">{action.actor}</td>
                <td className="px-3 py-2 font-mono text-xs">{action.action}</td>
                <td className="px-3 py-2">{describeTarget(action)}</td>
                <td className="px-3 py-2 text-slate-600">
                  {summarizeDetails(action)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <ErrorMessage message={error} />}
      {nextBefore !== null && (
        <div>
          <button
            type="button"
            onClick={loadOlder}
            disabled={pending}
            className={secondaryButtonClass}
          >
            {pending ? "Loading..." : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
