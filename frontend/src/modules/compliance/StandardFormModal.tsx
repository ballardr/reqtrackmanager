/**
 * Module: modules/compliance/StandardFormModal
 *
 * The create and edit dialog for a `ComplianceStandard` (§2), shared by the cross-organisation `/standards` list
 * (`StandardListPage.tsx`, create) and the `/standards/:standardId` workspace (`StandardWorkspacePage.tsx`, edit): one component
 * per pattern (docs/ux-style-guide.md Principle 8).
 * - Create also creates the mandatory first (draft) version, so a standard never has zero versions. When the caller can manage
 *   standards in more than one organisation an "Organisation" picker is the first field, hidden with only one candidate (as
 *   `ProjectListPage.tsx`'s "New project" dialog).
 * - Edit has no organisation field (the owning organisation never changes) but carries the Owner (a user or organisation
 *   group, never empty); create leaves the Owner to the backend, which makes the creator the owner until reassigned.
 */
import { useState } from "react";

import type { OrgUser, PrincipalRef } from "../../api/types";
import { principalRef, savedPrincipalDisplay } from "../../api/types";
import { Modal } from "../../components/Modal";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import type { ComplianceStandard } from "./types";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";
import { COMPLIANCE_HELP } from "./help";

export interface StandardFormValues {
  reference: string;
  name: string;
  description: string;
  issuing_organisation: string | null;
  initial_version_label: string;
  initial_version_effective_date: string | null;
  initial_version_change_note: string;
}

export interface EditableStandardFieldValues {
  name: string;
  description: string;
  issuing_organisation: string | null;
  owner: PrincipalRef;
}

interface StandardOrgOption {
  id: string;
  name: string;
}

export function StandardFormModal({
  initial,
  orgId,
  orgs,
  orgUsers = [],
  error,
  onCancel,
  onSave,
}: {
  /** Present in edit mode — the reference/version fields below are hidden,
   * and `onSave` receives just the editable fields. */
  initial?: ComplianceStandard;
  /** Fixed owning organisation — always given in edit mode, and in create
   * mode when the caller already knows there's exactly one candidate org
   * (so no `orgs` picker is needed). */
  orgId?: string;
  /** Candidate organisations to create the standard in, when the caller can manage standards in more than one (create mode
   * only). The picker renders only with more than one entry, as `ProjectListPage.tsx`'s "New project" org picker does. */
  orgs?: StandardOrgOption[];
  /** Organisation members offered by the Owner picker (edit mode). */
  orgUsers?: OrgUser[];
  /** A failed save's error message, rendered inside the open dialog above its button row (as `ProjectListPage.tsx`'s create
   * error), not as a toast, because the dialog stays open for the caller to correct and retry. */
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StandardFormValues | EditableStandardFieldValues, organizationId: string) => void;
}) {
  const [chosenOrgId, setSelectedOrgId] = useState("");
  // The organisation is derived, not copied into state by an effect: `orgs` is often still loading when the modal mounts, so a
  // caller with exactly one candidate picks it up when `orgs` arrives. A multi-organisation caller never gets an auto-filled
  // value (it could silently create the standard in whichever organisation loaded first), so the value stays blank until the
  // picker is used and Save stays disabled until then.
  const selectedOrgId = chosenOrgId || (orgId ?? (orgs?.length === 1 ? orgs[0].id : ""));
  const [reference, setReference] = useState(initial?.reference ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [issuingOrganisation, setIssuingOrganisation] = useState(initial?.issuing_organisation ?? "");
  const [owner, setOwner] = useState<PrincipalRef | null>(principalRef(initial?.owner));
  const [versionLabel, setVersionLabel] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [changeNote, setChangeNote] = useState("");

  const resolvedOrgId = orgId ?? selectedOrgId;
  const canSave =
    !!name.trim() &&
    !!resolvedOrgId &&
    (initial ? owner !== null : !!reference.trim() && !!versionLabel.trim());

  function handleSave() {
    if (initial) {
      if (owner) onSave({ name, description, issuing_organisation: issuingOrganisation || null, owner }, resolvedOrgId);
      return;
    }
    onSave(
      {
        reference,
        name,
        description,
        issuing_organisation: issuingOrganisation || null,
        initial_version_label: versionLabel,
        initial_version_effective_date: effectiveDate || null,
        initial_version_change_note: changeNote,
      },
      resolvedOrgId
    );
  }

  return (
    <Modal title={initial ? "Edit standard" : "New standard"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          {!initial && orgs && orgs.length > 1 && (
            <FormGridFull>
              <LabeledSelect helpNotNeeded required
                label="Organisation" value={selectedOrgId} onChange={setSelectedOrgId}
                options={orgs.map((o) => ({ value: o.id, label: o.name }))} placeholder={null}
              />
            </FormGridFull>
          )}
          {!initial && (
            <TextField help={COMPLIANCE_HELP.complianceStandardReference} required
              label="Reference"
              ariaLabel="Standard reference"
              value={reference}
              onChange={setReference}
              placeholder="e.g. ISO-27001"
              inputProps={{ autoFocus: !(orgs && orgs.length > 1) }}
            />
          )}
          <TextField helpNotNeeded required label="Name" ariaLabel="Standard name" value={name} onChange={setName} />
          <FormGridFull>
            <TextAreaField markdown helpNotNeeded label="Description" value={description} onChange={setDescription} rows={3} />
          </FormGridFull>
          <TextField help={COMPLIANCE_HELP.standardIssuer} label="Issuing organisation" value={issuingOrganisation} onChange={setIssuingOrganisation} />
          {initial && (
            <PrincipalFormField help={COMPLIANCE_HELP.standardOwner} required
              label="Owner"
              kinds={["user", "org_group"]}
              orgUsers={orgUsers}
              organizationId={resolvedOrgId}
              value={owner}
              display={savedPrincipalDisplay(owner, initial.owner)}
              onChange={setOwner}
              ariaLabel="Standard owner"
            />
          )}
          {!initial && (
            <>
              <FormGridFull>
                <h3 style={{ margin: "var(--space-3) 0 0" }}>Initial version</h3>
              </FormGridFull>
              <TextField help={COMPLIANCE_HELP.standardInitialVersion} required label="Initial version label" value={versionLabel} onChange={setVersionLabel} placeholder="e.g. 1.0" />
              <DateField help={COMPLIANCE_HELP.complianceEffectiveDate} label="Effective date" value={effectiveDate} onChange={setEffectiveDate} />
              <FormGridFull>
                <TextAreaField plainText="A version's one-line change note, listed in version histories" helpNotNeeded label="Change note" value={changeNote} onChange={setChangeNote} rows={2} />
              </FormGridFull>
            </>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={handleSave} saveDisabled={!canSave} />
      </div>
    </Modal>
  );
}
