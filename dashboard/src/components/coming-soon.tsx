/** Placeholder for a screen planned in a next release. */
export function ComingSoon({ title }: { title: string }) {
  return (
    <section>
      <h1 className="mb-2 text-xl font-semibold">{title}</h1>
      <p className="text-sm text-slate-600">This screen is not built yet.</p>
    </section>
  );
}
