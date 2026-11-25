/**
 * Module: components/OneTimeSecret
 *
 * Shows a credential the server returns once and never again (a newly issued personal access token): the title, a
 * sentence saying it cannot be retrieved later, the secret itself and a Copy button. One component so a person's own
 * token and a service user's token are presented, and warned about, the same way.
 */
import { useStrings } from "../context/TerminologyContext";

/**
 * @param title Heading ("Token created").
 * @param hint The sentence saying the secret is shown once.
 * @param secret The secret to show; it is held only in the caller's state and never stored by this component.
 * @param dismissLabel Text of the button that closes the notice (default "Cancel" is avoided: it implies an undo).
 * @param onDismiss Called when the person has copied the secret and closes the notice.
 */
export function OneTimeSecret({
  title, hint, secret, dismissLabel, onDismiss,
}: { title: string; hint: string; secret: string; dismissLabel: string; onDismiss: () => void }) {
  const strings = useStrings();
  return (
    <div className="stack" role="status" style={{ border: "1px solid var(--color-accent)", borderRadius: "var(--radius-md)", padding: "var(--space-4)" }}>
      <strong>{title}</strong>
      <p className="text-muted">{hint}</p>
      <code style={{ wordBreak: "break-all", background: "var(--color-surface-alt)", padding: "var(--space-3)", borderRadius: "var(--radius-sm)" }}>
        {secret}
      </code>
      <div className="row" style={{ gap: "var(--space-2)" }}>
        <button className="btn" onClick={() => void navigator.clipboard.writeText(secret)}>{strings.common.copy}</button>
        <button className="btn" onClick={onDismiss}>{dismissLabel}</button>
      </div>
    </div>
  );
}
