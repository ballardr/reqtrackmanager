/**
 * Module: components/PolicyAcceptDialog
 *
 * The dialog that asks a person to accept a required policy: its title, version and date, the full text and, in the
 * dialog header, an Accept action. The close button leaves without accepting; reading and signing out stay possible.
 *
 * It shows one policy at a time (the first the person has not accepted); after an acceptance the next one follows.
 */
import { useAcceptPolicy } from "../hooks/usePolicyAcceptance";
import { useStrings } from "../context/TerminologyContext";
import type { PendingPolicy } from "../api/types";
import { formatPlainDate } from "../utils/localDate";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { PolicyBodyView } from "./PolicyBodyView";

/**
 * @param policy The policy to accept.
 * @param onClose Called when the dialog is closed without accepting (also after the last acceptance).
 */
export function PolicyAcceptDialog({ policy, onClose }: { policy: PendingPolicy; onClose: () => void }) {
  const text = useStrings().policies;
  const accept = useAcceptPolicy();
  return (
    <Modal title={text.acceptDialogTitle} onClose={onClose} size="lg" dirty={false}>
      <div className="stack">
        <FormActions onCancel={onClose} saveLabel={text.accept} onSave={() => void accept(policy)} />
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <h2 style={{ margin: 0 }}>{policy.title}</h2>
          <div className="text-muted">
            {policy.organization_name && <span>{policy.organization_name}. </span>}
            {policy.effective_from && <span>{text.effectiveFrom(formatPlainDate(policy.effective_from))}. </span>}
            <span>{text.versionLine(policy.version, new Date(policy.published_at).toLocaleDateString())}</span>
          </div>
        </div>
        <PolicyBodyView body={policy.body} />
        <p className="text-muted">{text.acceptBody(policy.version)}</p>
      </div>
    </Modal>
  );
}
