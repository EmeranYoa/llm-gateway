/**
 * Build URLs whose search params carry the filters of a screen (period, tenant),
 * so a filtered view can be bookmarked and survives a reload.
 */

/**
 * The query string after setting `key` to `value`, other params kept.
 * A null or empty `value` removes the param. Returns `""` or `"?a=b&c=d"`.
 */
export function withSearchParam(
  current: URLSearchParams | string,
  key: string,
  value: string | null,
): string {
  const params = new URLSearchParams(current);
  if (value) {
    params.set(key, value);
  } else {
    params.delete(key);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** The overview filtered on a period, and on a tenant when one is given. */
export function overviewHref(period: string, tenant: string | null): string {
  const params = new URLSearchParams({ period });
  if (tenant) {
    params.set("tenant", tenant);
  }
  return `/?${params}`;
}
