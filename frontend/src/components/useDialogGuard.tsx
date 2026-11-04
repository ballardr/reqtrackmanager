/**
 * Module: components/useDialogGuard
 *
 * The unsaved-changes guard shared by `Modal` and `SidePanel`: every way of leaving a form dialog
 * (Escape, the header close button) goes through `requestClose`, which closes at once when nothing
 * is unsaved and otherwise asks first (`DiscardChangesDialog`). A click on the backdrop does not
 * close a dialog that holds a form. A browser tab close or reload while unsaved is warned about too.
 *
 * "Unsaved" is the caller's `dirty` value when it passes one (compared by value against what was
 * opened). A dialog that holds a form (it renders `FormActions`) but passes none is measured from the
 * DOM: the values of its inputs, textareas, selects and rich-text fields are recorded at the first
 * interaction and compared at close, so an edit that is undone reads as clean. A dialog that has finished
 * its work (a result view with `ResultActions`) is settled: it holds nothing unsaved whatever the earlier steps
 * edited, so it closes without asking. Dialogs without a form (viewers, pickers, confirms) are never dirty and
 * keep closing on the backdrop.
 *
 * Dependencies: `DiscardChangesDialog`; used by `Modal` and `SidePanel`.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { DiscardChangesDialog } from "./DiscardChangesDialog";
import type { DialogGuardFrame } from "./DialogHeader";

const CONTROLS = 'input, textarea, select, [contenteditable="true"]';

/** The editable values inside `root` as one comparable string. */
function readValues(root: HTMLElement): string {
  return Array.from(root.querySelectorAll<HTMLElement>(CONTROLS))
    .map((el) => {
      if (el instanceof HTMLInputElement) return el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value;
      if (el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return el.value;
      return el.innerHTML;
    })
    .join("\u0000");
}

/** What the guard gives its dialog. */
export interface DialogGuard {
  /** Close the dialog, asking first when it holds unsaved changes. Use it for Escape and the close button. */
  requestClose: () => void;
  /** True when a click on the backdrop may close the dialog (a dialog with no form and no `dirty`). */
  backdropCloses: boolean;
  /** Wiring for `DialogFrame`. */
  frame: DialogGuardFrame;
  /** The discard prompt while it is open, else null; render it beside the dialog. */
  prompt: ReactNode;
}

/**
 * @param onClose Closes the dialog for real (unmount); called when nothing is unsaved or the user discards.
 * @param dirty Whether the form has unsaved changes; omit it to have a form dialog measured from the DOM.
 * @param dismissOnBackdrop Overrides whether a backdrop click closes (default: only a dialog with no form and no `dirty`).
 */
export function useDialogGuard(onClose: () => void, dirty?: boolean, dismissOnBackdrop?: boolean): DialogGuard {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const baseline = useRef<string | null>(null);
  const [formCount, setFormCount] = useState(0);
  const settled = useRef(0);
  const [asking, setAsking] = useState(false);
  const hasForm = formCount > 0;
  const measured = dirty === undefined && hasForm;

  const registerForm = useCallback(() => {
    setFormCount((n) => n + 1);
    return () => setFormCount((n) => n - 1);
  }, []);

  // Record the form's values at the first interaction, before the person changes anything.
  useEffect(() => {
    const body = bodyRef.current;
    if (!measured || !body) return;
    const record = () => {
      if (baseline.current === null) baseline.current = readValues(body);
    };
    const events = ["focusin", "pointerdown", "keydown"] as const;
    events.forEach((name) => body.addEventListener(name, record, true));
    return () => events.forEach((name) => body.removeEventListener(name, record, true));
  }, [measured]);

  const registerSettled = useCallback(() => {
    settled.current += 1;
    return () => {
      settled.current -= 1;
    };
  }, []);

  const isDirty = useCallback((): boolean => {
    if (settled.current > 0) return false;
    if (dirty !== undefined) return dirty;
    const body = bodyRef.current;
    return !!body && baseline.current !== null && readValues(body) !== baseline.current;
  }, [dirty]);

  const guarded = dirty !== undefined || hasForm;
  useEffect(() => {
    if (!guarded) return;
    const warn = (event: BeforeUnloadEvent) => {
      if (isDirty()) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [guarded, isDirty]);

  const requestClose = useCallback(() => {
    if (isDirty()) setAsking(true);
    else onClose();
  }, [isDirty, onClose]);

  return {
    requestClose,
    backdropCloses: dismissOnBackdrop ?? !guarded,
    frame: { bodyRef, registerForm, registerSettled },
    prompt: asking ? <DiscardChangesDialog onKeepEditing={() => setAsking(false)} onDiscard={onClose} /> : null,
  };
}
