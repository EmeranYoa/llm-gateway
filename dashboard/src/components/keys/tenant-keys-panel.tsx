import type { Limits, TenantKeys } from "@/api/tenant-keys";
import { LocalDateTime } from "@/components/local-time";
import type { Locale } from "@/lib/i18n/locale";
import { richText } from "@/lib/i18n/rich-text";
import { getTranslator, type Translator } from "@/lib/i18n/translator";
import {
  clearCacheAction,
  revokeKeyAction,
  setLimitsAction,
} from "@/lib/key-actions";

import { CacheClearForm } from "./cache-clear-form";
import { LimitsForm } from "./limits-form";
import { RevokeKeyButton } from "./revoke-key-button";

/** The selected tenant: its limits, its keys, and the forms that change them. */
export function TenantKeysPanel({
  data,
  locale,
}: {
  data: TenantKeys;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg font-semibold">
        {t("keys.panel.title", { tenant: data.tenant })}
      </h2>

      <section aria-labelledby="limits-heading" className="flex flex-col gap-3">
        <h3 id="limits-heading" className="font-medium">
          {t("keys.panel.limits")}
        </h3>
        <LimitsTable
          own={data.limits}
          effective={data.effective_limits}
          t={t}
        />
        <LimitsForm
          key={data.tenant}
          action={setLimitsAction}
          tenant={data.tenant}
          effectiveLimits={data.effective_limits}
        />
      </section>

      <section aria-labelledby="keys-heading" className="flex flex-col gap-3">
        <h3 id="keys-heading" className="font-medium">
          {t("keys.panel.keys")}
        </h3>
        <KeysTable data={data} t={t} />
      </section>

      <section aria-labelledby="cache-heading" className="flex flex-col gap-3">
        <h3 id="cache-heading" className="font-medium">
          {t("keys.panel.cache")}
        </h3>
        <CacheClearForm
          key={data.tenant}
          action={clearCacheAction}
          tenant={data.tenant}
        />
      </section>
    </div>
  );
}

function LimitsTable({
  own,
  effective,
  t,
}: {
  own: Limits;
  effective: Limits;
  t: Translator;
}) {
  const rows = [
    {
      id: "rpm",
      label: t("keys.fields.rpm"),
      own: own.rpm,
      effective: effective.rpm,
    },
    {
      id: "tokens_per_day",
      label: t("keys.limits.tokensPerUtcDay"),
      own: own.tokens_per_day,
      effective: effective.tokens_per_day,
    },
  ];
  return (
    <table className="w-full max-w-lg rounded border border-slate-200 bg-white text-left text-sm">
      <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
        <tr>
          <th scope="col" className="px-3 py-2">
            {t("keys.limits.limit")}
          </th>
          <th scope="col" className="px-3 py-2">
            {t("keys.limits.own")}
          </th>
          <th scope="col" className="px-3 py-2">
            {t("keys.limits.applied")}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className="border-t border-slate-100">
            <th scope="row" className="px-3 py-2 font-normal">
              {row.label}
            </th>
            <td className="px-3 py-2">{row.own ?? t("keys.limits.default")}</td>
            <td className="px-3 py-2">
              {row.effective ?? t("keys.limits.noLimit")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KeysTable({ data, t }: { data: TenantKeys; t: Translator }) {
  if (data.keys.length === 0) {
    return <p className="text-sm text-slate-600">{t("keys.table.noKey")}</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-3 py-2">
              {t("keys.table.key")}
            </th>
            <th scope="col" className="px-3 py-2">
              {t("keys.table.created")}
            </th>
            <th scope="col" className="px-3 py-2">
              {t("keys.table.lastUsed")}
            </th>
            <th scope="col" className="px-3 py-2">
              {t("keys.table.status")}
            </th>
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">{t("keys.table.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.keys.map((key) => (
            <tr key={key.id} className="border-t border-slate-100 align-top">
              <td className="px-3 py-2 font-mono text-xs">{key.prefix}...</td>
              <td className="px-3 py-2 whitespace-nowrap">
                <LocalDateTime iso={key.created_at} />
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {key.last_used_at ? (
                  <LocalDateTime iso={key.last_used_at} />
                ) : (
                  t("keys.table.never")
                )}
              </td>
              <td className="px-3 py-2">
                {key.revoked_at ? (
                  <span className="text-slate-500">
                    {richText(t, "keys.table.revoked", {
                      time: <LocalDateTime iso={key.revoked_at} />,
                    })}
                  </span>
                ) : (
                  <span className="font-medium text-emerald-700">
                    {t("keys.table.active")}
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right">
                {key.revoked_at === null && (
                  <RevokeKeyButton
                    action={revokeKeyAction}
                    keyId={key.id}
                    prefix={key.prefix}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
