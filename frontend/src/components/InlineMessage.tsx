/**
 * Module: components/InlineMessage
 *
 * A one-line outcome message drawn where an action happened (an error under a failed save, a success note under an
 * upload), so every such line takes its colour from the theme's tokens and is announced to assistive technology.
 * Nothing is drawn for an empty message; errors are `role="alert"`, successes `role="status"`. A failure also shown
 * as a toast keeps only the toast; this is for a result that belongs beside its control.
 */
import type { ReactNode } from "react";

const TONE_COLOUR = { error: "var(--color-danger)", warning: "var(--color-warning)", success: "var(--color-accent)" } as const;

/**
 * @param tone `error` (the default), `warning` (a condition to act on soon, announced politely) or `success`.
 * @param children The message; nothing is drawn when it is empty, null or false.
 */
export function InlineMessage({ tone = "error", children }: { tone?: "error" | "warning" | "success"; children?: ReactNode }) {
  if (children === null || children === undefined || children === false || children === "") return null;
  return (
    <div role={tone === "error" ? "alert" : "status"} style={{ color: TONE_COLOUR[tone] }}>
      {children}
    </div>
  );
}
