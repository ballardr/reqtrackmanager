/**
 * Module: utils/sectionOrder
 *
 * Works out the order a record page shows its sections in, from the built-in order and the layers a person or a
 * project may have saved over it. Pure, so every record page that lets its sections be rearranged resolves the same way.
 */

/**
 * One layer over the built-in order: the keys it names come first, in its order; a key it does not name follows in
 * the built-in order, so a section added to the page later still appears; a key the page does not know is ignored.
 *
 * @param builtin Every section key the page has, in its built-in order.
 * @param layer A saved order, or null/empty for none.
 * @returns A permutation of `builtin`.
 */
export function applySectionOrder(builtin: readonly string[], layer: readonly string[] | null | undefined): string[] {
  if (!layer || layer.length === 0) return [...builtin];
  const known = new Set(builtin);
  const named = [...new Set(layer)].filter((key) => known.has(key));
  return [...named, ...builtin.filter((key) => !named.includes(key))];
}

/**
 * The order to show: the first non-empty layer wins (a person's own, then the project's), else the built-in order.
 *
 * @param builtin Every section key the page has, in its built-in order.
 * @param layers Saved orders, most specific first.
 * @returns A permutation of `builtin`.
 */
export function resolveSectionOrder(builtin: readonly string[], ...layers: (readonly string[] | null | undefined)[]): string[] {
  const layer = layers.find((l) => l && l.length > 0);
  return applySectionOrder(builtin, layer);
}

/**
 * Moves one key a step up or down.
 *
 * @param order The current order.
 * @param key The key to move.
 * @param direction -1 for up, 1 for down.
 * @returns A new array; the same order when the key is at that end.
 */
export function moveSection(order: readonly string[], key: string, direction: -1 | 1): string[] {
  const from = order.indexOf(key);
  const to = from + direction;
  if (from < 0 || to < 0 || to >= order.length) return [...order];
  const next = [...order];
  [next[from], next[to]] = [next[to], next[from]];
  return next;
}
