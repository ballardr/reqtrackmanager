/**
 * Module: components/recordActivityKey
 *
 * The refresh value a detail page gives `RecordActivity`, kept apart from the component so that file
 * exports only a component.
 */

/**
 * A value that changes whenever the record itself does (a lifecycle step, an edit), for a page to pass as
 * `refreshToken` so an Activity tab that is already open shows the change without being closed and reopened.
 *
 * @param record The record as the page holds it.
 */
export function recordActivityKey(record: { status?: string; updated_at?: string; version_number?: number }): string {
  return `${record.status ?? ""}|${record.updated_at ?? ""}|${record.version_number ?? ""}`;
}
