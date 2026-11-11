/**
 * Module: utils/storageLimit
 *
 * Conversion between a storage limit in bytes (what the API stores) and the amount-and-unit a person types (megabytes or
 * gigabytes), using the same 1024-based units as `formatFileSize`, so a limit reads back as it was entered.
 */

/** The units a limit is entered in. */
export type StorageUnit = "MB" | "GB";

const MB = 1024 * 1024;
const GB = 1024 * MB;

/**
 * @param bytes A limit in bytes, or null for none.
 * @returns The amount text and unit to show: gigabytes when the limit is a whole number of them, else megabytes
 *   (rounded to two decimals); an empty amount for null.
 */
export function splitStorageLimit(bytes: number | null): { amount: string; unit: StorageUnit } {
  if (bytes === null) return { amount: "", unit: "GB" };
  if (bytes >= GB && bytes % GB === 0) return { amount: String(bytes / GB), unit: "GB" };
  return { amount: String(Math.round((bytes / MB) * 100) / 100), unit: "MB" };
}

/**
 * @param amount The typed amount (empty for no limit).
 * @param unit The chosen unit.
 * @returns The limit in bytes, `null` for an empty amount, or `undefined` when the text is not a non-negative number.
 */
export function joinStorageLimit(amount: string, unit: StorageUnit): number | null | undefined {
  const text = amount.trim();
  if (text === "") return null;
  const value = Number(text);
  if (!Number.isFinite(value) || value < 0) return undefined;
  return Math.round(value * (unit === "GB" ? GB : MB));
}
