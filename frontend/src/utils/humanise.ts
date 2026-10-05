/**
 * Module: utils/humanise
 *
 * Turns a backend identifier into readable label text ("model_key" -> "Model
 * key"). For generated UI (the report parameter form) where core has no label
 * map for a module's own vocabulary; anything with a real label map must use
 * that instead (style guide Principle 12).
 *
 * @param value A snake_case identifier or a choice value.
 * @returns The value with underscores as spaces and the first letter capitalised.
 */
export function humanise(value: string | number): string {
  const text = String(value).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
