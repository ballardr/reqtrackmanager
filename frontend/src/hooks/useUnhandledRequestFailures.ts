/**
 * Module: hooks/useUnhandledRequestFailures
 *
 * Says so when a request failed and nothing on the page handled it. A page that loads with `.then(setRows)` and no
 * catch leaves its spinner up for ever when the request is refused, times out or never reaches the server; this shows the
 * reason once, with a Reload action, instead of leaving the person to wait. A failure a page does handle (it catches it
 * and shows its own message) never reaches this, and a refusal that ended the session is not shown, because the
 * person is already being taken to the sign-in page.
 *
 * Mounted once, by `App`, inside the toast provider.
 */
import { useEffect } from "react";

import { ApiError } from "../api/client";
import { useToast } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";

/** The same text is not shown again within this window (a server that is down fails many requests at once). */
const REPEAT_WINDOW_MS = 15_000;

/**
 * The text to show for a failure: the server's message when it is plain text, else a generic line (a validation
 * refusal carries a list that is not meant to be read as a sentence).
 *
 * @param error The failed request.
 * @param generic The line used when the message is not plain text.
 * @returns A one-line message.
 */
export function failureText(error: ApiError, generic: string): string {
  const message = error.message.trim();
  return message === "" || /^[[{]/.test(message) ? generic : message;
}

/**
 * Listens for requests that failed with no one handling them.
 *
 * Side effects: adds a `unhandledrejection` listener to the window for as long as the caller is mounted and shows an
 * error toast (staying until dismissed, with Reload) for each distinct failure.
 */
export function useUnhandledRequestFailures(): void {
  const { showToast } = useToast();
  const strings = useStrings();
  useEffect(() => {
    const shown = new Map<string, number>();
    const onRejection = (event: PromiseRejectionEvent) => {
      const reason: unknown = event.reason;
      if (!(reason instanceof ApiError) || reason.sessionEnded) return;
      const text = failureText(reason, strings.requestFailure.generic);
      const now = Date.now();
      const last = shown.get(text);
      if (last !== undefined && now - last < REPEAT_WINDOW_MS) return;
      shown.set(text, now);
      showToast(text, "error", {
        details: [strings.requestFailure.incomplete],
        action: { label: strings.requestFailure.reload, onClick: () => window.location.reload() },
      });
    };
    window.addEventListener("unhandledrejection", onRejection);
    return () => window.removeEventListener("unhandledrejection", onRejection);
  }, [showToast, strings]);
}
