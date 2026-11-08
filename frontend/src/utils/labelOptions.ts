/**
 * Module: utils/labelOptions
 *
 * Builds select options from an enum label map (`REQUIREMENT_STATUS_LABEL`), so a select lists exactly the labels the
 * rest of the product shows for that enum and its value type stays the enum, not `string`.
 */

/**
 * Builds select options from a label map, in the map's own order.
 *
 * @param labels The enum-value to display-label map.
 * @returns One `{ value, label }` option per key.
 */
export function labelOptions<K extends string>(labels: Record<K, string>): { value: K; label: string }[] {
  return (Object.keys(labels) as K[]).map((value) => ({ value, label: labels[value] }));
}
