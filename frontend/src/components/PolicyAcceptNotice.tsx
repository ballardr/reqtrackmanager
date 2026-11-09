/**
 * Module: components/PolicyAcceptNotice
 *
 * The notice shown on every signed-in page while a required policy is unaccepted, with a link to the Policies page,
 * and the dialog that opens once per browser session on sign-in so the text is in front of the person at once.
 *
 * Responsibilities: draw nothing when nothing is pending; open `PolicyAcceptDialog` for the first pending policy the
 * first time the list is non-empty in a session (remembered in `sessionStorage`, a per-viewer convenience that a
 * blocked store only makes repeat); the notice itself stays until every policy is accepted, because the server
 * refuses changes until then.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { acceptDialogShownKey, usePolicyAcceptance } from "../hooks/usePolicyAcceptance";
import { PolicyAcceptDialog } from "./PolicyAcceptDialog";

function alreadyShown(userId: string): boolean {
  try {
    return window.sessionStorage.getItem(acceptDialogShownKey(userId)) === "1";
  } catch {
    return false;
  }
}

function rememberShown(userId: string): void {
  try {
    window.sessionStorage.setItem(acceptDialogShownKey(userId), "1");
  } catch {
    /* storage unavailable: the dialog may open again */
  }
}

export function PolicyAcceptNotice() {
  const text = useStrings().policies;
  const userId = useAuth().user?.id ?? "";
  const { pending } = usePolicyAcceptance();
  const [closed, setClosed] = useState(false);
  const first = pending[0];
  // Open until closed, once per session; closing remembers it so a later page or reload does not ask again.
  const open = !closed && !alreadyShown(userId);

  if (!first) return null;
  return (
    <>
      <div role="status" className="row" style={{ gap: "var(--space-3)", padding: "var(--space-2) var(--space-4)", background: "var(--color-surface-alt)", borderBottom: "1px solid var(--color-border)" }}>
        <span>{text.acceptNotice(pending.length)}</span>
        <Link to={`/policies/${first.id}`}>{text.acceptNoticeLink}</Link>
      </div>
      {open && <PolicyAcceptDialog policy={first} onClose={() => { rememberShown(userId); setClosed(true); }} />}
    </>
  );
}
