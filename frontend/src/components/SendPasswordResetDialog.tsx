/**
 * Module: components/SendPasswordResetDialog
 *
 * The confirmation an organisation or server administrator sees before emailing a person a password-reset
 * link ("Send password reset link" in a user's action menu). One component for both tiers: the caller passes
 * the endpoint it is entitled to (`/orgs/{id}/users/{userId}/password-reset` or
 * `/system/users/{userId}/password-reset`).
 *
 * Responsibilities: ask once (a Tier 1 confirmation), call the endpoint, and report the outcome with a toast
 * (success, or the server's reason: no password to reset, email disabled, sent too recently).
 * The administrator never sees the link; it goes to the person's own address.
 */
import { api } from "../api/client";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { ConfirmDialog } from "./ConfirmDialog";

const strings = t();

/**
 * @param userName The person's display name, for the wording and the toast.
 * @param endpoint The POST endpoint that emails the link.
 * @param onClose Called when the dialog is dismissed or the request finishes.
 */
export function SendPasswordResetDialog({
  userName, endpoint, onClose,
}: {
  userName: string;
  endpoint: string;
  onClose: () => void;
}) {
  const { showToast } = useToast();

  async function send() {
    onClose();
    try {
      await api.post(endpoint);
      showToast(strings.passwordReset.sentToast(userName));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  return (
    <ConfirmDialog
      title={strings.passwordReset.sendLinkTitle(userName)}
      message={strings.passwordReset.sendLinkMessage}
      confirmLabel={strings.passwordReset.sendLinkConfirm}
      onConfirm={send}
      onCancel={onClose}
    />
  );
}
