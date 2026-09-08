/**
 * Module: modules/compliance/StandardFormModal
 *
 * The create/edit dialog for a `ComplianceStandard` (§2) — extracted out of
 * `StandardsPanel.tsx` (docs/compliance-module-plan.md Phase 18, "Compliance
 * Standards" as a first-class, cross-org, project-like nav entity) so both
 * the new cross-org `/standards` list page (`StandardListPage.tsx`, create)
 * and the per-standard `/standards/:standardId` workspace
 * (`StandardWorkspacePage.tsx`, edit) can open the same dialog rather than
 * each keeping its own copy — this codebase's "one component per pattern"
 * rule (docs/ux-style-guide.md Principle 8).
 *
 * Create mode always also creates the standard's mandatory first (draft)
 * version in the same dialog (a standard is never left with zero versions —
 * Phase 12's original design decision, unchanged here). When the caller can
 * manage standards in more than one organisation, an "Organisation" picker
 * is the dialog's first field — the exact same "org picker as the first
 * field of the same create dialog, hidden entirely when there's only one
 * candidate" shape `ProjectListPage.tsx`'s own "New project" dialog already
 * establishes, reused rather than inventing a separate org-selection step.
 * Edit mode has no organisation field at all — a standard's owning org
 * never changes after creation, and the caller (`StandardWorkspacePage.tsx`)
 * already knows it.
 */
import { useEffect, useState } from "react";

import { Modal } from "../../components/Modal";
import type { ComplianceStandard } from "./types";

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
}

interface StandardOrgOption {
  id: string;
  name: string;
}

export function StandardFormModal({
  initial,
  orgId,
  orgs,
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
  const [versionLabel, setVersionLabel] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [changeNote, setChangeNote] = useState("");

  const resolvedOrgId = orgId ?? selectedOrgId;
  const canSave =
    !!name.trim() &&
    !!resolvedOrgId &&
    (!!initial || (!!reference.trim() && !!versionLabel.trim()));

  function handleSave() {
    if (initial) {
      onSave({ name, description, issuing_organisation: issuingOrganisation || null }, resolvedOrgId);
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
    <Modal title={initial ? "Edit standard" : "New standard"} onClose={onCancel}>
      <div className="stack">
        {!initial && orgs && orgs.length > 1 && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Organisation</span>
            <select
              className="input"
              value={selectedOrgId}
              onChange={(e) => setSelectedOrgId(e.target.value)}
              aria-label="Organisation"
              autoFocus
            >
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </label>
        )}
        {!initial && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Reference</span>
            <input
              className="input"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="e.g. ISO-27001"
              aria-label="Standard reference"
              autoFocus={!(orgs && orgs.length > 1)}
            />
          </label>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Standard name" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Description</span>
          <textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Issuing organisation</span>
          <input className="input" value={issuingOrganisation} onChange={(e) => setIssuingOrganisation(e.target.value)} />
        </label>
        {!initial && (
          <>
            <h3 style={{ margin: "0.5rem 0 0" }}>Initial version</h3>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Initial version label</span>
              <input className="input" value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} placeholder="e.g. 1.0" aria-label="Initial version label" />
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Effective date</span>
              <input className="input" type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Change note</span>
              <textarea className="input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)} rows={2} />
            </label>
          </>
        )}
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" disabled={!canSave} onClick={handleSave}>
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
