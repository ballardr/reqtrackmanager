/**
 * Module: components/InlineMessage
 *
 * A one-line outcome message drawn where an action happened: an error under a failed save, or a short success
 * note under an upload. One component so every such line takes its colour from the theme's tokens and is announced
 * to assistive technology, instead of each page hand-writing a coloured `<div>`.
 *
 * Responsibilities: draw nothing for an empty message; mark errors `role="alert"` and successes `role="status"`.
 * A failure that is also shown as a toast keeps only the toast; this is for a result that belongs beside its control.
 */
import type { ReactNode } from "react";

/**
 * @param tone `error` (the default) or `success`.
 * @param children The message; nothing is drawn when it is empty, null or false.
 */
export function InlineMessage({ tone = "error", children }: { tone?: "error" | "success"; children?: ReactNode }) {
  if (children === null || children === undefined || children === false || children === "") return null;
  return (
    <div role={tone === "error" ? "alert" : "status"} style={{ color: tone === "error" ? "var(--color-danger)" : "var(--color-accent)" }}>
      {children}
    </div>
  );
}
