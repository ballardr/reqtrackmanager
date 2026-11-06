/**
 * Module: hooks/useBodyScrollLock
 *
 * Stops the page behind a modal dialog or side panel from scrolling while it is open, so a wheel or touch scroll
 * that reaches the end of the dialog's own body (or lands on the backdrop) does not move the page underneath.
 *
 * Responsibilities:
 * - Hide the viewport's scrolling (`overflow: hidden` on `<html>` and `<body>`) and pad `<body>` by the scrollbar's
 *   width so the page does not shift sideways when the scrollbar disappears.
 * - Count open dialogs, so a dialog opened over another one keeps the lock until the last one closes.
 *
 * Design decision: the lock is applied by the modal chrome itself (`ModalBase`, `SidePanel`), never by a caller, so
 * every dialog behaves the same; `Popover` does not lock because it is a small anchored layer, not a blocking one.
 */
import { useEffect } from "react";

let openDialogs = 0;
let saved: { htmlOverflow: string; bodyOverflow: string; bodyPaddingRight: string } | null = null;

/**
 * Locks page scrolling for as long as the calling component is mounted.
 *
 * Side effects: sets inline `overflow` and `padding-right` on `document.documentElement` and `document.body`, and
 * restores their previous values when the last dialog using the lock unmounts.
 */
export function useBodyScrollLock(): void {
  useEffect(() => {
    if (openDialogs === 0) {
      const html = document.documentElement;
      const body = document.body;
      saved = { htmlOverflow: html.style.overflow, bodyOverflow: body.style.overflow, bodyPaddingRight: body.style.paddingRight };
      const scrollbar = window.innerWidth - html.clientWidth;
      if (scrollbar > 0) {
        body.style.paddingRight = `${(parseFloat(getComputedStyle(body).paddingRight) || 0) + scrollbar}px`;
      }
      html.style.overflow = "hidden";
      body.style.overflow = "hidden";
    }
    openDialogs += 1;
    return () => {
      openDialogs -= 1;
      if (openDialogs === 0 && saved) {
        document.documentElement.style.overflow = saved.htmlOverflow;
        document.body.style.overflow = saved.bodyOverflow;
        document.body.style.paddingRight = saved.bodyPaddingRight;
        saved = null;
      }
    };
  }, []);
}
