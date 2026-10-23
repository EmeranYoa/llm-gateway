export type BadgeTone = "green" | "red" | "amber" | "orange" | "slate";

const TONES: Record<BadgeTone, string> = {
  green: "bg-emerald-50 text-emerald-900 ring-emerald-300",
  red: "bg-red-50 text-red-900 ring-red-300",
  amber: "bg-amber-50 text-amber-900 ring-amber-300",
  orange: "bg-orange-50 text-orange-900 ring-orange-300",
  slate: "bg-slate-100 text-slate-800 ring-slate-300",
};

type BadgeProps = {
  tone: BadgeTone;
  /** Shown as a tooltip: what the badge means. */
  title?: string;
  children: React.ReactNode;
};

/**
 * A short coloured label, such as a status. The colour only helps: the text
 * always says the same thing, so the badge reads without colours.
 */
export function Badge({ tone, title, children }: BadgeProps) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
