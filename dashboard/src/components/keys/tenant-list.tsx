import Link from "next/link";

/** The tenants, as links that select one in the URL (`/keys?tenant=name`). */
export function TenantList({
  names,
  selected,
}: {
  names: string[];
  selected: string | null;
}) {
  if (names.length === 0) {
    return (
      <p className="text-sm text-slate-600">
        No tenant yet: create a key to create the first one.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {names.map((name) => {
        const current = name === selected;
        return (
          <li key={name}>
            <Link
              href={{ pathname: "/keys", query: { tenant: name } }}
              aria-current={current ? "page" : undefined}
              className={
                current
                  ? "block rounded bg-slate-900 px-3 py-1.5 text-white"
                  : "block rounded px-3 py-1.5 text-slate-700 hover:bg-slate-100"
              }
            >
              {name}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
