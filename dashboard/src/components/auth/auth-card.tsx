import { LanguageSelector } from "@/components/language-selector";

type AuthCardProps = {
  title: string;
  intro?: string;
  /** Saves the language in the account; only for a signed-in operator. */
  saveLanguage?: (language: string) => Promise<{ saved: boolean }>;
  children: React.ReactNode;
};

/**
 * The frame of the screens shown outside the dashboard itself: sign-in, setup
 * of the first account, password change and account recovery. A small
 * centered card, with the language selector above it.
 */
export function AuthCard({
  title,
  intro,
  saveLanguage,
  children,
}: AuthCardProps) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 py-8">
      <div className="flex w-full max-w-sm justify-end">
        <LanguageSelector save={saveLanguage} />
      </div>
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-1 text-lg font-semibold">{title}</h1>
        {intro !== undefined && (
          <p className="mb-6 text-sm text-slate-600">{intro}</p>
        )}
        {children}
      </div>
    </main>
  );
}
