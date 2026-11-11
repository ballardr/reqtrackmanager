/**
 * Module: utils/dateTimeLocal
 *
 * Conversion between a UTC instant (ISO 8601, as the API stores and returns it) and the value of a
 * `datetime-local` input (the person's local wall-clock time, `YYYY-MM-DDTHH:mm`). The browser does every
 * conversion to and from local time; the server only ever sees and returns UTC.
 */

/**
 * @param iso A UTC instant (ISO 8601), or null.
 * @returns The same instant as local `YYYY-MM-DDTHH:mm` for a `datetime-local` input; "" for null or an invalid value.
 */
export function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * @param value A `datetime-local` input value in the person's local time, or "".
 * @returns The UTC instant (ISO 8601) it denotes; null for "" or an invalid value.
 */
export function localInputToIso(value: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
