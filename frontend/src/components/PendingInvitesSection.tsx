import { Send } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { PendingInvite } from "../api/types";
import { PENDING_INVITE_STATUS_LABEL, PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { CollapsibleSection } from "./CollapsibleSection";

/**
 * Lists a project's outstanding (unaccepted) `PendingInvite`s — sent via
 * the project-user picker's "invite by email" branch
 * (`ProjectAdminPage.tsx`'s `addExternalMember`/`UserAutocomplete`) — with
 * a single "Resend" action per row (Phase 3, docs/decisions.md: "resend a
 * stalled invite email"). Deliberately its own small, self-contained
 * component rather than interleaved into the per-group membership UI
 * below it on `ProjectAdminPage.tsx`'s "Project groups" tab: a pending
 * invite is project-scoped, not per-group, and this component fetches and
 * manages its own state so it can be relocated (e.g. onto a future
 * Members page) by just moving this one `<PendingInvitesSection />` usage
 * and its import, with no entanglement to touch on the page it's leaving.
 *
 * No cancel/revoke action — not asked for by the Phase 3 scope, and not
 * added speculatively (style guide: don't scope-creep a small, targeted
 * feature).
 */
export function PendingInvitesSection({ projectId }: { projectId: string }) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [invites, setInvites] = useState<PendingInvite[] | null>(null);
  const [resendingId, setResendingId] = useState<string | null>(null);

  async function load() {
    setInvites(await api.get<PendingInvite[]>(`/api/v1/projects/${projectId}/pending-invites`));
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function resend(invite: PendingInvite) {
    setResendingId(invite.id);
    try {
      await api.post(`/api/v1/projects/${projectId}/pending-invites/${invite.id}/resend`);
      showToast(strings.admin.resendInviteSuccess(invite.email));
      await load();
    } catch (err) {
      showToast(toErrorMessage(err, strings.admin.resendInviteError), "error");
    } finally {
      setResendingId(null);
    }
  }

  return (
    <CollapsibleSection sectionKey="projectAdmin.pendingInvites" title={strings.admin.pendingInvites} defaultCollapsed>
      <p className="text-muted" style={{ margin: 0 }}>{strings.admin.pendingInvitesHint}</p>
      {invites === null ? null : invites.length === 0 ? (
        <p className="text-muted">{strings.admin.noPendingInvites}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>{strings.admin.invitedEmail}</th>
                <th>{strings.admin.invitedRole}</th>
                <th>{strings.admin.invitedSent}</th>
                <th>{strings.admin.invitedStatus}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {invites.map((invite) => (
                <tr key={invite.id}>
                  <td>{invite.email}</td>
                  <td>{PROJECT_ROLE_LABEL[invite.role]}</td>
                  <td>{new Date(invite.created_at).toLocaleDateString()}</td>
                  <td>
                    <span className="badge">{PENDING_INVITE_STATUS_LABEL[invite.status]}</span>
                  </td>
                  <td>
                    <button
                      className="btn"
                      title={strings.admin.resendInviteAria(invite.email)}
                      aria-label={strings.admin.resendInviteAria(invite.email)}
                      disabled={resendingId === invite.id}
                      onClick={() => resend(invite)}
                    >
                      <Send size={14} /> {strings.admin.resendInvite}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </CollapsibleSection>
  );
}
