/**
 * Module: components/ServiceUserDetailModal
 *
 * One service user in a dialog: its details and review flags, its tokens (name, prefix, projects, expiry, last use,
 * who issued it, state), and the actions an organisation administrator has on it: edit, issue a token, revoke a
 * token, deactivate or reactivate, archive.
 *
 * Design decisions:
 * - A secret returned by Issue token is held here only until the person dismisses it (`OneTimeSecret`); closing the
 *   dialog discards it, and the list never receives it.
 * - Deactivate and revoke are recoverable (a new token can be issued), so they use the plain confirmation; archive
 *   hides the account for good and asks for its name to be typed.
 * - Every change is reported through `useMutation` (a success or failure Toast) and then reloaded from the server.
 *
 * Dependencies: `/api/v1/orgs/{id}/service-users/...` and the ordinary user deactivate and archive endpoints.
 */
import { useCallback, useState } from "react";

import { api } from "../api/client";
import {
  serviceUsersPath, type ServiceUser, type ServiceUserToken, type ServiceUserTokenCreated,
} from "../api/serviceUsers";
import type { ProjectListItem } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useMutation } from "../hooks/useMutation";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { InlineMessage } from "./InlineMessage";
import { Modal } from "./Modal";
import { OneTimeSecret } from "./OneTimeSecret";
import { PrincipalBadge } from "./PrincipalBadge";
import { ServiceBadge } from "./ServiceBadge";
import { ServiceUserFlags } from "./ServiceUserFlags";
import { ServiceUserTokenModal, type ServiceUserTokenDraft } from "./ServiceUserTokenModal";
import { Spinner } from "./Spinner";

type Confirm = { kind: "revoke"; token: ServiceUserToken } | { kind: "deactivate" } | { kind: "archive" } | null;

function tokenState(token: ServiceUserToken, text: ReturnType<typeof useStrings>["serviceUsers"]): { label: string; tone: "accent" | "muted" | "warning" } {
  if (token.revoked_at) return { label: text.tokenRevoked, tone: "muted" };
  if (new Date(token.expires_at) <= new Date()) return { label: text.tokenExpired, tone: "warning" };
  return { label: text.tokenActive, tone: "accent" };
}

/**
 * @param organizationId The organisation.
 * @param serviceUser The service user shown (re-read by the caller through `onChanged`).
 * @param projects The organisation's projects, for the token restriction.
 * @param onEdit Opens the edit form for this service user.
 * @param onChanged Called after a change so the list reloads.
 * @param onClose Closes the dialog.
 */
export function ServiceUserDetailModal({
  organizationId, serviceUser, projects, onEdit, onChanged, onClose,
}: {
  organizationId: string;
  serviceUser: ServiceUser;
  projects: ProjectListItem[];
  onEdit: () => void;
  onChanged: () => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.serviceUsers;
  const run = useMutation();
  const [tokens, setTokens] = useState<ServiceUserToken[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [issueError, setIssueError] = useState<string | null>(null);
  const [secret, setSecret] = useState<ServiceUserTokenCreated | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const base = `${serviceUsersPath(organizationId)}/${serviceUser.user_id}`;

  const load = useCallback(async () => {
    try {
      setTokens(await api.get<ServiceUserToken[]>(`${base}/pats`));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, text.loadFailed));
    }
  }, [base, text.loadFailed]);

  useLoadOnChange(load, [base]);

  async function issue(draft: ServiceUserTokenDraft) {
    setIssueError(null);
    try {
      const created = await api.post<ServiceUserTokenCreated>(`${base}/pats`, draft);
      setSecret(created);
      setIssuing(false);
      await load();
      onChanged();
    } catch (err) {
      setIssueError(toErrorMessage(err, strings.common.error));
    }
  }

  async function confirmed() {
    const pending = confirm;
    setConfirm(null);
    if (!pending) return;
    const ok =
      pending.kind === "revoke"
        ? await run(() => api.delete(`${base}/pats/${pending.token.id}`), "revoke", text.issueTokenNoun)
        : pending.kind === "deactivate"
          ? await run(
              () => api.post(`/api/v1/orgs/${organizationId}/users/${serviceUser.user_id}/deactivate`),
              { success: text.deactivatedToast, failure: text.deactivateFailed },
            )
          : await run(() => api.post(`/api/v1/orgs/${organizationId}/users/${serviceUser.user_id}/archive`), "archive", text.noun);
    if (!ok) return;
    await load();
    onChanged();
    if (pending.kind === "archive") onClose();
  }

  async function reactivate() {
    if (await run(() => api.post(`${base}/reactivate`), "reactivate", text.noun)) onChanged();
  }

  const state = serviceUser.is_archived ? text.statusArchived : serviceUser.is_active ? text.statusActive : text.statusDeactivated;
  return (
    <Modal title={text.detailsTitle(serviceUser.name)} onClose={onClose} size="lg" dirty={false}>
      <div className="stack">
        <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
          <ServiceBadge />
          <Badge tone={serviceUser.is_active ? "accent" : "muted"}>{state}</Badge>
          <ServiceUserFlags flags={serviceUser.flags} />
          <span style={{ flex: 1 }} />
          {!serviceUser.is_archived && <button className="btn" onClick={onEdit}>{text.edit}</button>}
          {serviceUser.is_active && <button className="btn" onClick={() => setConfirm({ kind: "deactivate" })}>{text.deactivate}</button>}
          {!serviceUser.is_active && !serviceUser.is_archived && <button className="btn" onClick={() => void reactivate()}>{text.reactivate}</button>}
          {!serviceUser.is_active && !serviceUser.is_archived && (
            <button className="btn btn-danger" onClick={() => setConfirm({ kind: "archive" })}>{text.archive}</button>
          )}
        </div>
        <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "var(--space-2) var(--space-4)", margin: 0 /* grid-text-ok: the first column holds the product's own labels */ }}>
          <dt className="text-muted">{text.description}</dt>
          <dd style={{ margin: 0, whiteSpace: "pre-wrap" }}>{serviceUser.description || "—"}</dd>
          <dt className="text-muted">{text.responsible}</dt>
          <dd style={{ margin: 0 }}><PrincipalBadge principal={serviceUser.responsible} placeholder={text.none} /></dd>
          <dt className="text-muted">{text.email}</dt>
          <dd style={{ margin: 0 }}>{serviceUser.email ?? text.noEmail}</dd>
          {serviceUser.created_by_display_name && (
            <>
              <dt className="text-muted">{text.createdByLabel}</dt>
              <dd style={{ margin: 0 }}>{serviceUser.created_by_display_name}</dd>
            </>
          )}
        </dl>

        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>{text.tokensHeading}</h3>
          {serviceUser.is_active && !serviceUser.is_archived && (
            <button className="btn btn-primary" onClick={() => { setIssueError(null); setIssuing(true); }}>{text.issueToken}</button>
          )}
        </div>
        {secret && (
          <OneTimeSecret
            title={text.tokenSecretTitle} hint={secret.notice || text.tokenSecretHint} secret={secret.token}
            dismissLabel={text.tokenSecretDismiss} onDismiss={() => setSecret(null)}
          />
        )}
        {loadError ? (
          <InlineMessage>{loadError}</InlineMessage>
        ) : !tokens ? (
          <Spinner />
        ) : tokens.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>{text.noTokens}</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table" aria-label={text.tokensHeading}>
              <thead>
                <tr>
                  <th>{text.tokenName}</th><th>{text.tokenPrefix}</th><th>{text.tokenProjects}</th><th>{text.tokenExpires}</th>
                  <th>{text.lastUsed}</th><th>{text.tokenIssuedBy}</th><th>{text.tokenState}</th><th />
                </tr>
              </thead>
              <tbody>
                {tokens.map((token) => {
                  const s = tokenState(token, text);
                  return (
                    <tr key={token.id}>
                      <td>{token.name}</td>
                      <td><code>{token.token_prefix}…</code></td>
                      <td>{token.allowed_projects.length === 0 ? text.tokenAllProjects : token.allowed_projects.map((p) => p.name).join(", ")}</td>
                      <td>{new Date(token.expires_at).toLocaleDateString()}</td>
                      <td>{token.last_used_at ? new Date(token.last_used_at).toLocaleString() : text.never}</td>
                      <td>{token.created_by_display_name ?? "—"}</td>
                      <td><Badge tone={s.tone}>{s.label}</Badge></td>
                      <td>
                        {!token.revoked_at && (
                          <button className="btn btn-danger" aria-label={text.revokeAria(token.name)} onClick={() => setConfirm({ kind: "revoke", token })}>
                            {text.revoke}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {issuing && (
        <ServiceUserTokenModal
          organizationId={organizationId} projects={projects} error={issueError}
          onCancel={() => setIssuing(false)} onSave={(draft) => void issue(draft)}
        />
      )}
      {confirm?.kind === "revoke" && (
        <ConfirmDialog title={text.revokeTitle} message={text.revokeConfirm} confirmLabel={text.revoke} onConfirm={() => void confirmed()} onCancel={() => setConfirm(null)} />
      )}
      {confirm?.kind === "deactivate" && (
        <ConfirmDialog
          title={text.deactivateTitle(serviceUser.name)} message={text.deactivateConfirm} confirmLabel={text.deactivate}
          onConfirm={() => void confirmed()} onCancel={() => setConfirm(null)}
        />
      )}
      {confirm?.kind === "archive" && (
        <ConfirmDialog
          title={text.archiveTitle(serviceUser.name)} message={text.archiveConfirm} confirmLabel={text.archive}
          requireTypedText={serviceUser.name} onConfirm={() => void confirmed()} onCancel={() => setConfirm(null)}
        />
      )}
    </Modal>
  );
}
