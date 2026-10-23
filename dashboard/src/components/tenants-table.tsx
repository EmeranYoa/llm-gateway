import Link from "next/link";

import type { TenantStatistics } from "@/api/client";
import { DEFINITIONS } from "@/lib/definitions";
import { formatCount, formatMoney, formatRate } from "@/lib/format";
import type { Period } from "@/lib/period";
import { overviewHref } from "@/lib/search-params";

type Column = {
  label: string;
  /** Shown as the `title` of the header cell. */
  definition?: string;
  value: (tenant: TenantStatistics) => string;
};

const COLUMNS: Column[] = [
  {
    label: "Requests",
    definition: DEFINITIONS.requests,
    value: (t) => formatCount(t.requests),
  },
  {
    label: "Tokens",
    definition: DEFINITIONS.tokens,
    value: (t) => formatCount(t.tokens),
  },
  {
    label: "Cost",
    definition: DEFINITIONS.cost,
    value: (t) => formatMoney(t.cost_usd),
  },
  {
    label: "Error rate",
    definition: DEFINITIONS.errorRate,
    value: (t) => formatRate(t.error_rate),
  },
  {
    label: "Cache hits",
    definition: DEFINITIONS.cacheHits,
    value: (t) => formatCount(t.cache_hits),
  },
  {
    label: "Saved cost",
    definition: DEFINITIONS.savedCost,
    value: (t) => formatMoney(t.saved_cost_usd),
  },
  {
    label: "Quota refusals",
    definition: DEFINITIONS.quotaRefusals,
    value: (t) => formatCount(t.quota_refusals),
  },
];

type TenantsTableProps = {
  tenants: TenantStatistics[];
  /** The period of the figures, carried by the links to the overview. */
  period: Period;
};

/**
 * One row per tenant. Clicking a row opens the overview filtered on that tenant
 * and the same period (the tenant name is a link that covers the whole row).
 */
export function TenantsTable({ tenants, period }: TenantsTableProps) {
  if (tenants.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        No tenant yet. Create one with{" "}
        <code className="font-mono text-xs">
          python -m app.admin create-key --tenant name
        </code>
        .
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-600">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">
              Tenant
            </th>
            {COLUMNS.map((column) => (
              <th
                key={column.label}
                scope="col"
                title={column.definition}
                className="px-4 py-2 text-right font-medium"
              >
                {column.label}
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
                  key={column.label}
                  className="px-4 py-2 text-right text-slate-900 tabular-nums"
                >
                  {column.value(tenant)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
