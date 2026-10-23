import { AdminApiError, getMe } from "@/api/client";
import { ApiErrorNotice } from "@/components/api-error-notice";

export default async function OverviewPage() {
  let name: string;
  try {
    ({ name } = await getMe());
  } catch (error) {
    if (error instanceof AdminApiError) {
      return <ApiErrorNotice error={error} />;
    }
    throw error; // a redirect to /login, or a bug
  }

  return (
    <section>
      <h1 className="mb-2 text-xl font-semibold">Overview</h1>
      <p className="text-sm text-slate-600">
        Signed in as <span className="font-medium text-slate-900">{name}</span>
      </p>
    </section>
  );
}
