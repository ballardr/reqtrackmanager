import { t } from "../i18n/strings";

const strings = t();

/**
 * Persistent "showing X of Y" result count for a paginated, filterable list
 * (2026-08 UX audit roadmap) — lives in `FilterPanel`'s always-visible
 * header, unlike `LoadMoreButton`'s "(loaded/total)" text, which disappears
 * entirely once every page has loaded (`LoadMoreButton.tsx`).
 *
 * `matching` is the filtered/searched count (the existing `X-Total-Count`
 * header); `total` is the unfiltered mandatory-scope count
 * (`X-Total-Unfiltered-Count`). Two display states:
 *  - no filter/search narrowing the result set (`matching === total`):
 *    just the total, e.g. "57 total".
 *  - a filter or search term active (`matching < total`): both counts,
 *    e.g. "Showing 12 matching · 57 total".
 */
export function ResultCount({ matching, total }: { matching: number; total: number }) {
  return (
    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
      {matching < total ? strings.common.resultCountMatching(matching, total) : strings.common.resultCountTotal(total)}
    </div>
  );
}
