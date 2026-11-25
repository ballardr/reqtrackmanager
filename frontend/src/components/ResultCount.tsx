import { t } from "../i18n/strings";

const strings = t();

/**
 * Persistent "showing X of Y" result count for a paginated, filterable list, shown in `FilterPanel`'s always-visible
 * header (unlike `LoadMoreButton`'s "(loaded/total)" text, which disappears once every page has loaded).
 *
 * `matching` is the filtered or searched count (`X-Total-Count`); `total` is the unfiltered mandatory-scope count
 * (`X-Total-Unfiltered-Count`). With no narrowing (`matching === total`) it shows the total ("57 total"); with a
 * filter or search active (`matching < total`) both ("Showing 12 matching · 57 total").
 */
export function ResultCount({ matching, total }: { matching: number; total: number }) {
  return (
    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
      {matching < total ? strings.common.resultCountMatching(matching, total) : strings.common.resultCountTotal(total)}
    </div>
  );
}
