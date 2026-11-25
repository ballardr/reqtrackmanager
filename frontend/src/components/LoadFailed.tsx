/**
 * Module: components/LoadFailed
 *
 * What a page shows in place of its spinner when the data it needs could not be loaded: the one-line reason and a Retry
 * button, so a refused, timed-out or lost request never leaves the person watching a spinner.
 *
 * A page whose record is missing shows its own not-found message instead (the style guide's record-header rule); this is
 * for a list or a settings page whose request failed.
 */
import { useStrings } from "../context/TerminologyContext";

/**
 * @param message What could not be loaded, as a sentence (`strings.requestFailure.loadFailed(...)`).
 * @param onRetry Starts the load again; the page clears its failed state before it does.
 */
export function LoadFailed({ message, onRetry }: { message: string; onRetry: () => void }) {
  const strings = useStrings();
  return (
    <div className="row" role="alert">
      <span style={{ color: "var(--color-danger)" }}>{message}</span>
      <button type="button" className="btn btn-sm" onClick={onRetry}>
        {strings.requestFailure.retry}
      </button>
    </div>
  );
}
