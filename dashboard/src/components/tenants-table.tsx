import Link from "next/link";

import type { TenantStatistics } from "@/api/client";
import { formatCount, formatMoney, formatRate } from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { richText } from "@/lib/i18n/rich-text";
import { getTranslator, type Translator } from "@/lib/i18n/translator";
import type { Period } from "@/lib/period";
import { overviewHref } from "@/lib/search-params";

type Column = {
  /** The figure: its header (`tenants.<id>`) and its definition (`definitions.<id>`). */
  id:
    | "requests"
    | "tokens"
    | "cost"
    | "errorRate"
    | "cacheHits"
    | "savedCost"
    | "quotaRefusals";
  value: (tenant: TenantStatistics, locale: Locale, t: Translator) => string;
};

const COLUMNS: Column[] = [
  {
    id: "requests",
    value: (tenant, locale) => formatCount(locale, tenant.requests),
  },
  {
    id: "tokens",
    value: (tenant, locale) => formatCount(locale, tenant.tokens),
  },
  {
    id: "cost",
    // An unknown price is never counted as 0: say how many answers are left out.
    value: (tenant, locale, t) =>
      tenant.unpriced_requests > 0
        ? t("tenants.costWithUnpriced", {
            cost: formatMoney(locale, tenant.cost_usd),
            count: tenant.unpriced_requests,
          })
        : formatMoney(locale, tenant.cost_usd),
  },
  {
    id: "errorRate",
    value: (tenant, locale) => formatRate(locale, tenant.error_rate),
  },
  {
    id: "cacheHits",
    value: (tenant, locale) => formatCount(locale, tenant.cache_hits),
  },
  {
    id: "savedCost",
    value: (tenant, locale) => formatMoney(locale, tenant.saved_cost_usd),
  },
  {
    id: "quotaRefusals",
    value: (tenant, locale) => formatCount(locale, tenant.quota_refusals),
  },
];

type TenantsTableProps = {
  tenants: TenantStatistics[];
  /** The period of the figures, carried by the links to the overview. */
  period: Period;
  locale: Locale;
};

/**
 * One row per tenant. Clicking a row opens the overview filtered on that tenant
 * and the same period (the tenant name is a link that covers the whole row).
 */
export function TenantsTable({ tenants, period, locale }: TenantsTableProps) {
  const t = getTranslator(locale);
  if (tenants.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        {richText(t, "tenants.empty", {
          command: (
            <code className="font-mono text-xs">
              python -m app.admin create-key --tenant name
            </code>
          ),
        })}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-600">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">
              {t("tenants.tenant")}
            </th>
            {COLUMNS.map((column) => (
              <th
                key={column.id}
                scope="col"
                title={t(`definitions.${column.id}`)}
                className="px-4 py-2 text-right font-medium"
              >
                {t(`tenants.${column.id}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {tenants.map((tenant) => (
            <tr
              key={tenant.tenant}
              className="relative focus-within:bg-sky-50 hover:bg-slate-50"
            >
              <th scope="row" className="px-4 py-2 text-left font-medium">
                <Link
                  href={overviewHref(period, tenant.tenant)}
                  className="text-sky-800 after:absolute after:inset-0 hover:underline focus:outline-none"
                >
                  {tenant.tenant}
                </Link>
              </th>
              {COLUMNS.map((column) => (
                <td
                  key={column.id}
                  className="px-4 py-2 text-right text-slate-900 tabular-nums"
                >
                  {column.value(tenant, locale, t)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
