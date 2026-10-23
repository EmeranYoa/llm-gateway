import type { Metadata } from "next";

import { LocaleProvider } from "@/lib/i18n/client";
import { getI18n, getLocale } from "@/lib/i18n/server";

import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.title"), description: t("app.description") };
}

/**
 * The language of the request (`lang` cookie, else `Accept-Language`) sets
 * the `lang` of the page and is given to client components.
 */
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = await getLocale();
  return (
    <html lang={locale}>
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <LocaleProvider locale={locale}>{children}</LocaleProvider>
      </body>
    </html>
  );
}
