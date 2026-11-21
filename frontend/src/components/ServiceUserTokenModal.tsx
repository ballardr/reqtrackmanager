/**
 * Module: components/ServiceUserTokenModal
 *
 * Issues a personal access token for a service user: a name, an optional restriction to some of the organisation's
 * projects, and an expiry date pre-filled with the longest the organisation allows (the same ceiling the person's own
 * token form shows). The token always belongs to this organisation only. Saving is the caller's; the secret that comes
 * back is shown once through `OneTimeSecret`.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { ProjectListItem } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { CheckboxField, DateField, TextField } from "./FormFields";
import { FieldCaption } from "./FieldHelp";
import { FormActions } from "./FormActions";
import { FormGrid, FormGridFull } from "./FormGrid";
import { Modal } from "./Modal";

/** What the form sends. */
export interface ServiceUserTokenDraft {
  name: string;
  allowed_project_ids: string[];
  requested_expires_at?: string;
}

/**
 * @param organizationId The service user's organisation.
 * @param projects The organisation's projects, for the optional restriction.
 * @param error A save error to show in the header.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the values to send.
 */
export function ServiceUserTokenModal({
  organizationId, projects, error, onCancel, onSave,
}: {
  organizationId: string;
  projects: ProjectListItem[];
  error?: string | null;
  onCancel: () => void;
  onSave: (draft: ServiceUserTokenDraft) => void;
}) {
  const strings = useStrings();
  const text = strings.serviceUsers;
  const [name, setName] = useState("");
  const [projectIds, setProjectIds] = useState<Set<string>>(new Set());
  const [expiry, setExpiry] = useState("");
  const [expiryEdited, setExpiryEdited] = useState(false);
  const [maxExpiresAt, setMaxExpiresAt] = useState<string | null>(null);

  // The longest the organisation allows is shown as the starting value, so nobody has to look it up; a date the person
  // chose themselves is left alone.
  useLoadOnChange(async () => {
    const { max_expires_at } = await api.get<{ max_expires_at: string }>(
      `/api/v1/me/pats/max-lifetime?organization_ids=${encodeURIComponent(organizationId)}`,
    );
    setMaxExpiresAt(max_expires_at);
    if (!expiryEdited) setExpiry(max_expires_at.slice(0, 10));
  }, [organizationId]);

  const tooLong = !!(maxExpiresAt && expiry && new Date(expiry) > new Date(maxExpiresAt));

  function toggle(projectId: string) {
    setProjectIds((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  }

  return (
    <Modal title={text.issueTokenTitle} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField
            label={text.tokenNameField} value={name} onChange={setName} required placeholder={text.tokenNamePlaceholder}
            help={strings.help.serviceUserTokenName} inputProps={{ maxLength: 255 }}
          />
          <DateField
            label={text.tokenExpiry} value={expiry} help={strings.help.tokenExpiry}
            onChange={(next) => { setExpiryEdited(true); setExpiry(next); }}
            hint={tooLong && maxExpiresAt ? (
              <span style={{ color: "var(--color-danger)" }}>{text.tokenExpiryTooLong.replace("{date}", new Date(maxExpiresAt).toLocaleDateString())}</span>
            ) : undefined}
          />
          <FormGridFull>
            <div className="stack" style={{ gap: "var(--space-1)" }} role="group" aria-label={text.tokenProjectsField}>
              <FieldCaption label={text.tokenProjectsField} help={strings.help.serviceUserTokenProjects} />
              {projects.length === 0 ? (
                <span className="text-muted">{text.tokenNoProjects}</span>
              ) : (
                projects.map((project) => (
                  <CheckboxField
                    helpNotNeeded key={project.id} label={project.name}
                    checked={projectIds.has(project.id)} onChange={() => toggle(project.id)}
                  />
                ))
              )}
            </div>
          </FormGridFull>
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} saveLabel={text.issueToken}
          saveDisabled={!name.trim() || tooLong}
          onSave={() => onSave({
            name: name.trim(), allowed_project_ids: Array.from(projectIds),
            requested_expires_at: expiry ? new Date(expiry).toISOString() : undefined,
          })}
        />
      </div>
    </Modal>
  );
}
