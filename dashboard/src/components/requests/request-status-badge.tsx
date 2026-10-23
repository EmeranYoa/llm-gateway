import { Badge, type BadgeTone } from "@/components/badge";
import type { Locale } from "@/lib/i18n/locale";
import { getTranslator } from "@/lib/i18n/translator";
import type { RequestStatus } from "@/lib/request-filters";
import { en } from "@/messages/en";

const STATUS_TONES: Record<RequestStatus, BadgeTone> = {
  answered: "green",
  failed: "red",
  client_error: "amber",
  cancelled: "slate",
};

/** The status of a request, with its definition in a tooltip. */
export function RequestStatusBadge({
  status,
  locale,
}: {
  status: RequestStatus;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  return (
    <Badge
      tone={STATUS_TONES[status]}
      title={t(`requestStatus.definitions.${status}`)}
    >
      {t(`requestStatus.labels.${status}`)}
    </Badge>
  );
}

/** `provider/model`, or a muted "not answered". */
export function AnsweredBy({
  provider,
  model,
  locale,
}: {
  provider: string | null;
  model: string | null;
  locale: Locale;
}) {
  if (provider === null || model === null) {
    return (
      <span className="text-slate-500">
        {getTranslator(locale)("requests.notAnswered")}
      </span>
    );
  }
  return (
    <span className="font-mono text-xs break-all">
      {provider}/{model}
    </span>
  );
}

/**
 * What the response cache did (`hit`, `miss`, `bypass`, `unavailable`), or
 * "off" when the alias does not use it. A value added to the gateway after this
 * dashboard is shown as it is.
 */
export function cacheLabel(cache: string | null, locale: Locale): string {
  const value = cache ?? "off";
  if (!Object.hasOwn(en.cache, value)) {
    return value;
  }
  return getTranslator(locale)(`cache.${value as keyof typeof en.cache}`);
}
