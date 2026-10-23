"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId } from "react";

import { type Period, PERIOD_LABELS, PERIODS } from "@/lib/period";
import { withSearchParam } from "@/lib/search-params";

/**
 * Filters of a screen, kept in the URL search params (`?period=7d&tenant=acme`):
 * a filtered view can be bookmarked and survives a reload. Changing a filter
 * navigates to the new URL; the server page reads the params and loads the data.
 * The current value comes from the server page, which applies the defaults.
 */

/** Navigate to the current page with one search param changed, the others kept. */
function useSetSearchParam(): (key: string, value: string | null) => void {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  return (key, value) => {
    const query = withSearchParam(searchParams.toString(), key, value);
    router.push(`${pathname}${query}`, { scroll: false });
  };
}

type SelectFilterProps = {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
};

function SelectFilter({ label, value, options, onChange }: SelectFilterProps) {
  const id = useId();
  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor={id} className="text-slate-600">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-900 focus:ring-2 focus:ring-sky-600 focus:outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Choose the period of the report: writes `?period=24h|7d|30d`. */
export function PeriodFilter({ value }: { value: Period }) {
  const setSearchParam = useSetSearchParam();
  return (
    <SelectFilter
      label="Period"
      value={value}
      options={PERIODS.map((period) => ({
        value: period,
        label: PERIOD_LABELS[period],
      }))}
      onChange={(period) => setSearchParam("period", period)}
    />
  );
}

const ALL_TENANTS = "";

type TenantFilterProps = {
  /** The selected tenant, or null for every tenant. */
  value: string | null;
  /** Names of the tenants to choose from. The selected one is always offered. */
  tenants: string[];
};

/** Choose one tenant or all of them: writes `?tenant=<name>`, or removes it for all. */
export function TenantFilter({ value, tenants }: TenantFilterProps) {
  const setSearchParam = useSetSearchParam();
  const names = [...tenants].sort((a, b) => a.localeCompare(b));
  if (value !== null && !names.includes(value)) {
    names.unshift(value);
  }
  return (
    <SelectFilter
      label="Tenant"
      value={value ?? ALL_TENANTS}
      options={[
        { value: ALL_TENANTS, label: "All tenants" },
        ...names.map((name) => ({ value: name, label: name })),
      ]}
      onChange={(tenant) => setSearchParam("tenant", tenant || null)}
    />
  );
}
