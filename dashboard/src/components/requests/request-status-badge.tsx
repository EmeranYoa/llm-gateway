import { Badge, type BadgeTone } from "@/components/badge";
import { REQUEST_STATUS_DEFINITIONS } from "@/lib/definitions";
import {
  REQUEST_STATUS_LABELS,
  type RequestStatus,
} from "@/lib/request-filters";

const STATUS_TONES: Record<RequestStatus, BadgeTone> = {
  answered: "green",
  failed: "red",
  client_error: "amber",
  cancelled: "slate",
};

/** The status of a request, with its definition in a tooltip. */
export function RequestStatusBadge({ status }: { status: RequestStatus }) {
  return (
    <Badge
      tone={STATUS_TONES[status]}
      title={REQUEST_STATUS_DEFINITIONS[status]}
    >
      {REQUEST_STATUS_LABELS[status]}
    </Badge>
  );
}

/** `provider/model`, or a muted "not answered". */
export function AnsweredBy({
  provider,
  model,
}: {
  provider: string | null;
  model: string | null;
}) {
  if (provider === null || model === null) {
    return <span className="text-slate-500">not answered</span>;
  }
  return (
    <span className="font-mono text-xs break-all">
      {provider}/{model}
    </span>
  );
}

/** What the response cache did, or "off" when the alias does not use it. */
export function cacheLabel(cache: string | null): string {
  return cache ?? "off";
}
