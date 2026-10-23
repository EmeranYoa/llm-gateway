import Link from "next/link";

import {
  AdminApiError,
  getRequest,
  keepApiError,
  type RequestDetail,
} from "@/api/client";
import { ApiErrorNotice } from "@/components/api-error-notice";
import { LocalDateTime, TimeZoneName } from "@/components/local-time";
import {
  AnsweredBy,
  cacheLabel,
  RequestStatusBadge,
} from "@/components/requests/request-status-badge";
import { RoutingPath } from "@/components/requests/routing-path";
import {
  formatCount,
  formatDuration,
  formatMoney,
  noValue,
} from "@/lib/format";
import { getI18n } from "@/lib/i18n/server";
import type { Locale } from "@/lib/i18n/locale";
import { richText } from "@/lib/i18n/rich-text";
import { getTranslator } from "@/lib/i18n/translator";
import { parseRequestFilters, requestsHref } from "@/lib/request-filters";

/**
 * One request: its summary and its routing path, to debug it. The search params
 * are those of the list it was opened from, so the back link returns there.
 * It does not refresh by itself: a request does not change once logged.
 */
export default async function RequestDetailPage({
  params,
  searchParams,
}: PageProps<"/requests/[requestId]">) {
  const { requestId } = await params;
  const { filters, cursor } = parseRequestFilters(await searchParams);

  const { locale, t } = await getI18n();
  const detail = await getRequest(requestId).catch(keepApiError);

  return (
    <section className="flex flex-col gap-4">
      <Link
        href={requestsHref(filters, cursor)}
        className="self-start text-sm text-sky-800 hover:underline"
      >
        {t("requestDetail.back")}
      </Link>
      <h1 className="text-xl font-semibold">
        {richText(t, "requestDetail.title", {
          id: (
            <span className="font-mono text-base break-all">{requestId}</span>
          ),
        })}
      </h1>
      {detail instanceof AdminApiError ? (
        detail.status === 404 ? (
          <div
            role="alert"
            className="rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          >
            <p className="font-medium">{t("requestDetail.notFound")}</p>
            <p>{t("requestDetail.notFoundHint")}</p>
          </div>
        ) : (
          <ApiErrorNotice error={detail} locale={locale} />
        )
      ) : (
        <>
          <RequestOverview request={detail} locale={locale} />
          <section
            aria-labelledby="path-heading"
            className="flex flex-col gap-3"
          >
            <h2 id="path-heading" className="text-lg font-semibold">
              {t("requestDetail.pathTitle")}
            </h2>
            <p className="text-sm text-slate-600">
              {t("requestDetail.pathIntro")}
            </p>
            <RoutingPath steps={detail.routing_path} locale={locale} />
          </section>
        </>
      )}
    </section>
  );
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-slate-900 tabular-nums">{value}</dd>
    </div>
  );
}

/** The summary of a request: when, who, which alias, and how it ended. */
function RequestOverview({
  request,
  locale,
}: {
  request: RequestDetail;
  locale: Locale;
}) {
  const t = getTranslator(locale);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <dl
        aria-label={t("requestDetail.summary")}
        className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3 lg:grid-cols-4"
      >
        <Item
          label={t("requestDetail.received")}
          value={<LocalDateTime iso={request.created_at} seconds />}
        />
        <Item
          label={t("requestDetail.tenant")}
          value={request.tenant ?? noValue(locale)}
        />
        <Item
          label={t("requestDetail.alias")}
          value={<span className="font-mono text-xs">{request.alias}</span>}
        />
        <Item
          label={t("requestDetail.status")}
          value={<RequestStatusBadge status={request.status} locale={locale} />}
        />
        <Item
          label={t("requestDetail.httpStatus")}
          value={request.status_code ?? noValue(locale)}
        />
        <Item
          label={t("requestDetail.answeredBy")}
          value={
            <AnsweredBy
              provider={request.provider}
              model={request.model}
              locale={locale}
            />
          }
        />
        <Item
          label={t("requestDetail.attempts")}
          value={formatCount(locale, request.attempts)}
        />
        <Item
          label={t("requestDetail.stream")}
          value={request.stream ? t("requests.yes") : t("requests.no")}
        />
        <Item
          label={t("requestDetail.latency")}
          value={formatDuration(locale, request.latency_ms)}
        />
        <Item
          label={t("requestDetail.cost")}
          value={formatMoney(locale, request.cost_usd)}
        />
        <Item
          label={t("requestDetail.cache")}
          value={cacheLabel(request.cache, locale)}
        />
      </dl>
      <p className="mt-3 text-xs text-slate-600">
        <TimeZoneName />
      </p>
    </div>
  );
}
