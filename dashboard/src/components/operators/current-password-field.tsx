"use client";

import { Field } from "@/components/auth/form-parts";
import { useTranslator } from "@/lib/i18n/client";

/**
 * The current password of the signed-in operator, asked again by every action
 * on accounts (re-authentication). `idPrefix` keeps the ids of the page unique.
 */
export function CurrentPasswordField({ idPrefix }: { idPrefix: string }) {
  const t = useTranslator();
  return (
    <Field
      idPrefix={idPrefix}
      name="currentPassword"
      label={t("operators.currentPassword")}
      type="password"
      autoComplete="current-password"
      hint={t("operators.currentPasswordHint")}
    />
  );
}
