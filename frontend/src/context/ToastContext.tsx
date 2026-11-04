import { Check, TriangleAlert, X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type ToastKind = "success" | "error";

/** What a toast can carry beyond its one line of text. */
export interface ToastOptions {
  /** A button on the toast (typically Undo); clicking it runs `onClick` and dismisses the toast. */
  action?: { label: string; onClick: () => void };
  /** Extra lines under the text. A toast with details stays until dismissed, so they can be read. */
  details?: string[];
}

interface ToastMessage extends ToastOptions {
  id: number;
  text: string;
  kind: ToastKind;
}

interface ToastContextValue {
  /** Shows a toast; auto-dismisses after ~4s or on manual close. `kind`
   * defaults to "success" since that's the far more common case (see
   * `showErrorToast` for the common error-handling shorthand). With
   * `options.details` it stays until dismissed. Returns the toast's id for
   * `dismissToast`. */
  showToast: (text: string, kind?: ToastKind, options?: ToastOptions) => number;
  /** Removes a toast early (for example when what its Undo button would undo is no longer there). */
  dismissToast: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

const AUTO_DISMISS_MS = 4000;

/**
 * Style guide "Pattern: confirmation, in two tiers — and feedback,
 * always" / Principle 7 ("every mutation ends with feedback") — one
 * shared success/error toast, fired from `useToast()` anywhere in the
 * tree, replacing the ad hoc per-page "did it work?" silence found
 * almost everywhere outside the CSV import wizard's own
 * one-off summary card.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const showToast = useCallback(
    (text: string, kind: ToastKind = "success", options?: ToastOptions) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, text, kind, ...options }]);
      if (!options?.details?.length) setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
      return id;
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ showToast, dismissToast: dismiss }}>
      {children}
      {createPortal(
        <div className="toast-stack" role="status" aria-live="polite">
          {toasts.map((toast) => (
            <div key={toast.id} className={`toast${toast.kind === "error" ? " toast-error" : ""}`}>
              {toast.kind === "error" ? <TriangleAlert size={16} /> : <Check size={16} />}
              <div className="toast-body">
                <span>{toast.text}</span>
                {toast.details && (
                  <ul className="toast-details">
                    {toast.details.map((line, index) => <li key={index}>{line}</li>)}
                  </ul>
                )}
              </div>
              {toast.action && (
                <button
                  type="button"
                  className="toast-action"
                  onClick={() => {
                    toast.action?.onClick();
                    dismiss(toast.id);
                  }}
                >
                  {toast.action.label}
                </button>
              )}
              <button
                type="button"
                className="toast-dismiss"
                onClick={() => dismiss(toast.id)}
                aria-label="Dismiss notification"
                title="Dismiss notification"
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

/** Common shorthand: report the message from a caught error (falling back
 * to a generic one) as an error-kind toast. */
export function toErrorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}
