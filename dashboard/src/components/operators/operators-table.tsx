"use client";

import { Fragment, useRef, useState } from "react";

import { Badge } from "@/components/badge";
import {
  secondaryButtonClass,
  SuccessMessage,
} from "@/components/keys/form-feedback";
import { LocalDateTime } from "@/components/local-time";
import { useBrowserTimeZone } from "@/lib/browser-hooks";
import { useTranslator } from "@/lib/i18n/client";
import {
  type Operator,
  type OperatorActionKind,
  operatorActions,
} from "@/lib/operator-forms";

import { AccountPanel, type OperatorFormAction } from "./account-panel";

type OperatorsTableProps = {
  operators: Operator[];
  /** The signed-in operator, marked "you"; null when the account is unknown. */
  currentUsername: string | null;
  /** The server actions of the rows. Props, so tests can pass fake ones. */
  actions: Record<OperatorActionKind, OperatorFormAction>;
};

type OpenPanel = { operatorId: number; kind: OperatorActionKind };

const COLUMN_COUNT = 4;

/**
 * Every operator account, with the actions it offers (see `operatorActions`).
 * An action opens its form under the row; one form is open at a time. A
 * success closes it and says what changed.
 */
export function OperatorsTable({
  operators,
  currentUsername,
  actions,
}: OperatorsTableProps) {
  const t = useTranslator();
  const timeZone = useBrowserTimeZone();
  const [open, setOpen] = useState<OpenPanel | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The button that opened the form: it gets the focus back on Cancel.
  const opener = useRef<HTMLButtonElement | null>(null);

  function openPanel(panel: OpenPanel, button: HTMLButtonElement) {
    opener.current = button;
    setNotice(null);
    setOpen(panel);
  }

  function cancel() {
    setOpen(null);
    opener.current?.focus();
  }

  function done(message: string) {
    setOpen(null);
    setNotice(message);
  }

  if (operators.length === 0) {
    return <p className="text-sm text-slate-600">{t("operators.empty")}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {notice !== null && <SuccessMessage>{notice}</SuccessMessage>}
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
            <tr>
              <th scope="col" className="px-3 py-2">
                {t("operators.columns.username")}
              </th>
              <th scope="col" className="px-3 py-2">
                {t("operators.columns.status")}
              </th>
              <th scope="col" className="px-3 py-2">
                {t("operators.columns.lastSignIn")}
              </th>
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">
                  {t("operators.columns.actions")}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {operators.map((operator) => {
              const panel = open?.operatorId === operator.id ? open.kind : null;
              return (
                <Fragment key={operator.id}>
                  <tr className="border-t border-slate-100 align-top">
                    <th scope="row" className="px-3 py-2 font-medium">
                      <span className="flex flex-wrap items-center gap-2">
                        {operator.username}
                        {operator.username === currentUsername && (
                          <Badge tone="slate">{t("operators.you")}</Badge>
                        )}
                      </span>
                    </th>
                    <td className="px-3 py-2">
                      <StatusBadges operator={operator} />
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {operator.last_sign_in_at === null ? (
                        t("operators.neverSignedIn")
                      ) : (
                        <LocalDateTime iso={operator.last_sign_in_at} />
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap justify-end gap-2">
                        {operatorActions(
                          operator,
                          currentUsername,
                          operators,
                        ).map((kind) => (
                          <button
                            key={kind}
                            type="button"
                            aria-label={t(`operators.${kind}.openLabel`, {
                              username: operator.username,
                            })}
                            aria-expanded={panel === kind}
                            onClick={(event) =>
                              openPanel(
                                { operatorId: operator.id, kind },
                                event.currentTarget,
                              )
                            }
                            className={secondaryButtonClass}
                          >
                            {t(`operators.${kind}.open`)}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                  {panel !== null && (
                    <tr>
                      <td colSpan={COLUMN_COUNT} className="px-3 pb-3">
                        <AccountPanel
                          key={panel}
                          operator={operator}
                          kind={panel}
                          action={actions[panel]}
                          onDone={done}
                          onCancel={cancel}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-600">
        {t("operators.timeZone", { zone: timeZone })}
      </p>
    </div>
  );
}

/** Enabled or disabled, and whether the password must be changed. */
function StatusBadges({ operator }: { operator: Operator }) {
  const t = useTranslator();
  return (
    <span className="flex flex-wrap gap-2">
      {operator.enabled ? (
        <Badge tone="green" title={t("operators.enabledHint")}>
          {t("operators.enabled")}
        </Badge>
      ) : (
        <Badge tone="slate" title={t("operators.disabledHint")}>
          {t("operators.disabled")}
        </Badge>
      )}
      {operator.must_change_password && (
        <Badge tone="amber" title={t("operators.mustChangePasswordHint")}>
          {t("operators.mustChangePassword")}
        </Badge>
      )}
    </span>
  );
}
