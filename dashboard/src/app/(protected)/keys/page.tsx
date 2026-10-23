import { AdminApiError } from "@/api/client";
import { listTenantNames } from "@/api/client";
import { getTenantKeys, listActions } from "@/api/tenant-keys";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { ActionHistory } from "@/components/keys/action-history";
import { CreateKeyForm } from "@/components/keys/create-key-form";
import { TimeZoneName } from "@/components/local-time";
import { TenantKeysPanel } from "@/components/keys/tenant-keys-panel";
import { TenantList } from "@/components/keys/tenant-list";
import { createKeyAction, loadActionsAction } from "@/lib/key-actions";

/**
 * Keys screen: tenants, their keys and limits, their cache, and the history of
 * admin actions. It does not refresh by itself (it would disturb a form being
 * filled); each server action revalidates it instead.
 */

type Loaded<T> = { data: T } | { error: AdminApiError };

/** Load one part of the page; an error of the admin API is shown in that part only. */
async function load<T>(call: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { data: await call() };
  } catch (error) {
    if (error instanceof AdminApiError) {
      return { error };
    }
    throw error; // a redirect to /login or /session-expired, or a bug
  }
}

export default async function KeysPage({ searchParams }: PageProps<"/keys">) {
  const { tenant } = await searchParams;
  const selected = typeof tenant === "string" && tenant !== "" ? tenant : null;

  const [names, actions, tenantKeys] = await Promise.all([
    load(listTenantNames),
    load(() => listActions()),
    selected === null ? null : load(() => getTenantKeys(selected)),
  ]);
  const knownNames = "data" in names ? names.data : [];

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="mb-1 text-xl font-semibold">Keys</h1>
        <p className="text-sm text-slate-600">
          Manage the API keys and limits of tenants. Gateways see changes within
          60 seconds.
        </p>
        <p className="text-xs text-slate-600">
          <TimeZoneName />
        </p>
      </header>

      <section
        aria-labelledby="create-heading"
        className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <h2 id="create-heading" className="text-lg font-semibold">
          Create a key
        </h2>
        <CreateKeyForm
          action={createKeyAction}
          tenants={knownNames}
          defaultTenant={selected ?? undefined}
        />
      </section>

      <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
        <nav aria-labelledby="tenants-heading">
          <h2 id="tenants-heading" className="mb-2 text-lg font-semibold">
            Tenants
          </h2>
          {"error" in names ? (
            <ApiErrorNotice error={names.error} />
          ) : (
            <TenantList names={names.data} selected={selected} />
          )}
        </nav>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          {tenantKeys === null ? (
            <p className="text-sm text-slate-600">
              Select a tenant to see its limits and keys.
            </p>
          ) : "error" in tenantKeys ? (
            <ApiErrorNotice error={tenantKeys.error} />
          ) : (
            <TenantKeysPanel data={tenantKeys.data} />
          )}
        </div>
      </div>

      <section
        aria-labelledby="history-heading"
        className="flex flex-col gap-3"
      >
        <h2 id="history-heading" className="text-lg font-semibold">
          History of admin actions
        </h2>
        {"error" in actions ? (
          <ApiErrorNotice error={actions.error} />
        ) : (
          <ActionHistory
            // A new action changes the first page: start again from it.
            key={actions.data.actions[0]?.id ?? "empty"}
            firstPage={actions.data}
            loadMore={loadActionsAction}
          />
        )}
      </section>
    </div>
  );
}
