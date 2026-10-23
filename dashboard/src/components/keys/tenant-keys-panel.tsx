import type { Limits, TenantKeys } from "@/api/tenant-keys";
import {
  clearCacheAction,
  revokeKeyAction,
  setLimitsAction,
} from "@/lib/key-actions";

import { CacheClearForm } from "./cache-clear-form";
import { LimitsForm } from "./limits-form";
import { LocalTime } from "./local-time";
import { RevokeKeyButton } from "./revoke-key-button";

/** The selected tenant: its limits, its keys, and the forms that change them. */
export function TenantKeysPanel({ data }: { data: TenantKeys }) {
  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-lg font-semibold">Tenant {data.tenant}</h2>

      <section aria-labelledby="limits-heading" className="flex flex-col gap-3">
        <h3 id="limits-heading" className="font-medium">
          Limits
        </h3>
        <LimitsTable own={data.limits} effective={data.effective_limits} />
        <LimitsForm
          key={data.tenant}
          action={setLimitsAction}
          tenant={data.tenant}
          effectiveLimits={data.effective_limits}
        />
      </section>

      <section aria-labelledby="keys-heading" className="flex flex-col gap-3">
        <h3 id="keys-heading" className="font-medium">
          Keys
        </h3>
        <KeysTable data={data} />
      </section>

      <section aria-labelledby="cache-heading" className="flex flex-col gap-3">
        <h3 id="cache-heading" className="font-medium">
          Cache
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

function LimitsTable({ own, effective }: { own: Limits; effective: Limits }) {
  const rows = [
    { label: "Requests per minute", own: own.rpm, effective: effective.rpm },
    {
      label: "Tokens per day (UTC day)",
      own: own.tokens_per_day,
      effective: effective.tokens_per_day,
    },
  ];
  return (
    <table className="w-full max-w-lg rounded border border-slate-200 bg-white text-left text-sm">
      <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
        <tr>
          <th scope="col" className="px-3 py-2">
            Limit
          </th>
          <th scope="col" className="px-3 py-2">
            Own
          </th>
          <th scope="col" className="px-3 py-2">
            Applied
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-t border-slate-100">
            <th scope="row" className="px-3 py-2 font-normal">
              {row.label}
            </th>
            <td className="px-3 py-2">{row.own ?? "default"}</td>
            <td className="px-3 py-2">{row.effective ?? "no limit"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KeysTable({ data }: { data: TenantKeys }) {
  if (data.keys.length === 0) {
    return <p className="text-sm text-slate-600">This tenant has no key.</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs text-slate-600 uppercase">
          <tr>
            <th scope="col" className="px-3 py-2">
              Key
            </th>
            <th scope="col" className="px-3 py-2">
              Created
            </th>
            <th scope="col" className="px-3 py-2">
              Last used
            </th>
            <th scope="col" className="px-3 py-2">
              Status
            </th>
            <th scope="col" className="px-3 py-2">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.keys.map((key) => (
            <tr key={key.id} className="border-t border-slate-100 align-top">
              <td className="px-3 py-2 font-mono text-xs">{key.prefix}...</td>
              <td className="px-3 py-2 whitespace-nowrap">
                <LocalTime value={key.created_at} />
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {key.last_used_at ? (
                  <LocalTime value={key.last_used_at} />
                ) : (
                  "never"
                )}
              </td>
              <td className="px-3 py-2">
                {key.revoked_at ? (
                  <span className="text-slate-500">
                    Revoked <LocalTime value={key.revoked_at} />
                  </span>
                ) : (
                  <span className="font-medium text-emerald-700">Active</span>
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
