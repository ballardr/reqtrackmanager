/**
 * Module: modules/compliance/StandardFormModal
 *
 * The create/edit dialog for a `ComplianceStandard` (§2) — extracted out of
 * `StandardsPanel.tsx` ("Compliance
 * Standards" as a first-class, cross-org, project-like nav entity) so both
 * the new cross-org `/standards` list page (`StandardListPage.tsx`, create)
 * and the per-standard `/standards/:standardId` workspace
 * (`StandardWorkspacePage.tsx`, edit) can open the same dialog rather than
 * each keeping its own copy — this codebase's "one component per pattern"
 * rule (docs/ux-style-guide.md Principle 8).
 *
 * Create mode always also creates the standard's mandatory first (draft)
 * version in the same dialog (a standard is never left with zero versions). When the caller can
 * manage standards in more than one organisation, an "Organisation" picker
 * is the dialog's first field — the exact same "org picker as the first
 * field of the same create dialog, hidden entirely when there's only one
 * candidate" shape `ProjectListPage.tsx`'s own "New project" dialog already
 * establishes, reused rather than inventing a separate org-selection step.
 * Edit mode has no organisation field at all — a standard's owning org
 * never changes after creation, and the caller (`StandardWorkspacePage.tsx`)
 * already knows it. Edit mode does carry the standard's Owner (a user or an
 * organisation group, never empty); create mode leaves it to the backend,
 * which makes the creator the owner until it is reassigned from the edit
 * dialog.
 */
import { useEffect, useState } from "react";

import type { OrgUser, PrincipalRef } from "../../api/types";
import { principalRef, savedPrincipalDisplay } from "../../api/types";
import { Modal } from "../../components/Modal";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import type { ComplianceStandard } from "./types";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { FormActions } from "../../components/FormActions";
import { DateField, TextAreaField, TextField } from "../../components/FormFields";

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
  /** Candidate organisations to create the standard in, when the caller can
   * manage standards in more than one (create mode only). The picker only
   * actually renders when this has more than one entry — mirrors
   * `ProjectListPage.tsx`'s own "New project" org picker exactly. */
  orgs?: StandardOrgOption[];
  /** Organisation members offered by the Owner picker (edit mode). */
  orgUsers?: OrgUser[];
  /** A failed save's error message, rendered inside the still-open dialog —
   * mirrors `ProjectListPage.tsx`'s own inline create-error placement
   * (inside the `Modal`, above its button row), not a toast, since the
   * dialog stays open for the caller to correct and retry. */
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StandardFormValues | EditableStandardFieldValues, organizationId: string) => void;
}) {
  const [selectedOrgId, setSelectedOrgId] = useState(orgId ?? (orgs?.length === 1 ? orgs[0].id : ""));
  // `orgs` is frequently still loading (an async fetch on the caller's own
  // page, e.g. `StandardListPage.tsx`'s `reload()`) at the exact moment
  // this modal first mounts — `useState`'s initializer above only runs
  // once, so a caller with genuinely exactly one candidate org, whose
  // `orgs` prop is still `[]`/loading at mount, would otherwise be stuck
  // with `selectedOrgId === ""` forever, permanently disabling Save with
  // no picker ever shown to fix it (no `orgs.length > 1`, so no UI
  // surfaces the problem either). Auto-fills only for that single-
  // candidate case, once `orgs` finishes loading — **never** for a
  // multi-org caller: an earlier version of this effect auto-filled from
  // `orgs[0].id` whenever nothing had been chosen yet, without checking
  // `orgs.length`, which silently picked whichever organisation happened
  // to load first (not necessarily the one shown as the picker's first
  // option, since the fill could race ahead of the picker's own re-render)
  // — a real, found-in-verification bug that could create a standard in
  // the wrong organisation with no error and no visual sign anything went
  // wrong. For `orgs.length > 1`, `selectedOrgId` is left blank until the
  // caller explicitly chooses in the picker — Save stays correctly
  // disabled until they do, exactly like the pre-existing case where
  // `orgs` hasn't loaded at all yet.
  useEffect(() => {
    if (!selectedOrgId && (orgId || orgs?.length === 1)) {
      setSelectedOrgId(orgId ?? orgs![0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, orgs]);
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
              <LabeledSelect
                label="Organisation" value={selectedOrgId} onChange={setSelectedOrgId}
                options={orgs.map((o) => ({ value: o.id, label: o.name }))} placeholder={null}
              />
            </FormGridFull>
          )}
          {!initial && (
            <TextField
              label="Reference"
              ariaLabel="Standard reference"
              value={reference}
              onChange={setReference}
              placeholder="e.g. ISO-27001"
              inputProps={{ autoFocus: !(orgs && orgs.length > 1) }}
            />
          )}
          <TextField label="Name" ariaLabel="Standard name" value={name} onChange={setName} />
          <FormGridFull>
            <TextAreaField label="Description" value={description} onChange={setDescription} rows={3} />
          </FormGridFull>
          <TextField label="Issuing organisation" value={issuingOrganisation} onChange={setIssuingOrganisation} />
          {initial && (
            <PrincipalFormField
              label="Owner"
              kinds={["user", "org_group"]}
              orgUsers={orgUsers}
              organizationId={resolvedOrgId}
              value={owner}
              display={savedPrincipalDisplay(owner, initial.owner)}
              onChange={setOwner}
              ariaLabel="Standard owner"
              placeholder="Select an owner…"
            />
          )}
          {!initial && (
            <>
              <FormGridFull>
                <h3 style={{ margin: "0.5rem 0 0" }}>Initial version</h3>
              </FormGridFull>
              <TextField label="Initial version label" value={versionLabel} onChange={setVersionLabel} placeholder="e.g. 1.0" />
              <DateField label="Effective date" value={effectiveDate} onChange={setEffectiveDate} />
              <FormGridFull>
                <TextAreaField label="Change note" value={changeNote} onChange={setChangeNote} rows={2} />
              </FormGridFull>
            </>
          )}
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={handleSave} saveDisabled={!canSave} />
      </div>
    </Modal>
  );
}
