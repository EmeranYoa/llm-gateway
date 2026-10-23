"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId } from "react";

import { useTranslator } from "@/lib/i18n/client";
import { type Period, PERIODS } from "@/lib/period";
import { REQUEST_STATUSES, type RequestStatus } from "@/lib/request-filters";
import { CURSOR_PARAM, withSearchParam } from "@/lib/search-params";

/**
 * Filters of a screen, kept in the URL search params (`?period=7d&tenant=acme`):
 * a filtered view can be bookmarked and survives a reload. Changing a filter
 * navigates to the new URL; the server page reads the params and loads the data.
 * The current value comes from the server page, which applies the defaults.
 */

/**
 * Navigate to the current page with one search param changed, the others kept.
 * The page cursor of a paged list is removed: new filters start from the first page.
 */
function useSetSearchParam(): (key: string, value: string | null) => void {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  return (key, value) => {
    const current = new URLSearchParams(searchParams.toString());
    current.delete(CURSOR_PARAM);
    const query = withSearchParam(current, key, value);
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
  const t = useTranslator();
  return (
    <SelectFilter
      label={t("period.label")}
      value={value}
      options={PERIODS.map((period) => ({
        value: period,
        label: t(`period.${period}`),
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
  const t = useTranslator();
  const names = [...tenants].sort((a, b) => a.localeCompare(b));
  if (value !== null && !names.includes(value)) {
    names.unshift(value);
  }
  return (
    <SelectFilter
      label={t("filters.tenant")}
      value={value ?? ALL_TENANTS}
      options={[
        { value: ALL_TENANTS, label: t("filters.allTenants") },
        ...names.map((name) => ({ value: name, label: name })),
      ]}
      onChange={(tenant) => setSearchParam("tenant", tenant || null)}
    />
  );
}

const ALL_STATUSES = "";

/** Choose the status of the requests: writes `?status=failed`, or removes it for all. */
export function RequestStatusFilter({
  value,
}: {
  /** The selected status, or null for every status. */
  value: RequestStatus | null;
}) {
  const setSearchParam = useSetSearchParam();
  const t = useTranslator();
  return (
    <SelectFilter
      label={t("filters.status")}
      value={value ?? ALL_STATUSES}
      options={[
        { value: ALL_STATUSES, label: t("filters.allStatuses") },
        ...REQUEST_STATUSES.map((status) => ({
          value: status,
          label: t(`requestStatus.labels.${status}`),
        })),
      ]}
      onChange={(status) => setSearchParam("status", status || null)}
    />
  );
}

type AliasFilterProps = {
  /** The selected alias, or null for every alias. */
  value: string | null;
  /** Aliases to suggest while typing (the admin API has no list of aliases). */
  suggestions: string[];
};

/**
 * Type a model alias: writes `?alias=<name>` when the form is sent, or removes
 * it when the field is empty. Any alias can be typed; `suggestions` only help.
 */
export function AliasFilter({ value, suggestions }: AliasFilterProps) {
  const setSearchParam = useSetSearchParam();
  const t = useTranslator();
  const id = useId();
  const listId = `${id}-aliases`;
  return (
    <form
      role="search"
      aria-label={t("filters.aliasSearch")}
      className="flex items-center gap-2 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        const typed = new FormData(event.currentTarget).get("alias");
        setSearchParam("alias", String(typed ?? "").trim() || null);
      }}
    >
      <label htmlFor={id} className="text-slate-600">
        {t("filters.alias")}
      </label>
      <input
        // A new value from the server (back button, cleared filter) resets the field.
        key={value ?? ""}
        id={id}
        name="alias"
        type="search"
        defaultValue={value ?? ""}
        list={listId}
        placeholder={t("filters.allAliases")}
        className="w-36 rounded border border-slate-300 bg-white px-2 py-1 text-slate-900 focus:ring-2 focus:ring-sky-600 focus:outline-none"
      />
      <datalist id={listId}>
        {[...new Set(suggestions)].sort().map((alias) => (
          <option key={alias} value={alias} />
        ))}
      </datalist>
      <button
        type="submit"
        className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-700 hover:bg-slate-100 focus:ring-2 focus:ring-sky-600 focus:outline-none"
      >
        {t("filters.apply")}
      </button>
    </form>
  );
}
