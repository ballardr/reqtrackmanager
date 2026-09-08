/**
 * Module: modules/compliance/StandardsPanel
 *
 * §2's compliance-standard catalogue: a searchable `DirectoryTable` +
 * `FilterPanel` list (style guide "Pattern: directories at scale"), a
 * `Modal` create flow (Principle 3 — "create is a layer"), and a
 * `SidePanel` detail view (edit fields, archive/unarchive, and §4's version
 * lifecycle: list versions, create a new one — optionally cloned from an
 * existing one — publish/retire). Selecting a version drills into
 * `VersionWorkspace` (full content-column width, not nested inside the
 * already-narrow `SidePanel` — see that component's own docstring).
 *
 * Owner reassignment has no dedicated control here — the edit form always
 * resubmits the standard's current `owner_id` unchanged (a deliberate Phase
 * 12 scope trim: §2 only requires "Owner" exist as an attribute, and a
 * proper reassignment control needs a user picker (`UserAutocomplete`) this
 * phase didn't wire up for a single field with no other consumer yet — see
 * docs/compliance-module-plan.md's Phase 12 notes).
 */
import { useEffect, useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { DirectoryColumn } from "../../components/DirectoryTable";
import { DirectoryTable } from "../../components/DirectoryTable";
import { FilterCheckbox, FilterPanel } from "../../components/FilterPanel";
import { Modal } from "../../components/Modal";
import { SidePanel } from "../../components/SidePanel";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { VersionWorkspace } from "./VersionWorkspace";
import {
  COMPLIANCE_STANDARD_VERSION_STATUS_LABEL,
  type ComplianceActionType,
  type ComplianceStandard,
  type ComplianceStandardVersion,
} from "./types";

export function StandardsPanel({ orgId, actionTypes }: { orgId: string; actionTypes: ComplianceActionType[] }) {
  const { showToast } = useToast();
  const [standards, setStandards] = useState<ComplianceStandard[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);

  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<ComplianceStandard | null>(null);
  const [editing, setEditing] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<ComplianceStandard | null>(null);

  const [versions, setVersions] = useState<ComplianceStandardVersion[] | null>(null);
  const [creatingVersion, setCreatingVersion] = useState(false);
  const [activeVersion, setActiveVersion] = useState<ComplianceStandardVersion | null>(null);

  async function reload() {
    try {
      setStandards(await complianceApi.listStandards(orgId, includeArchived));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load compliance standards. The Compliance module may not be enabled for this organisation."));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, includeArchived]);

  async function openStandard(standard: ComplianceStandard) {
    setSelected(standard);
    setVersions(null);
    setActiveVersion(null);
    try {
      setVersions(await complianceApi.listStandardVersions(orgId, standard.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load versions."), "error");
    }
  }

  async function reloadVersions(standard: ComplianceStandard) {
    setVersions(await complianceApi.listStandardVersions(orgId, standard.id));
  }

  async function handleArchiveToggle() {
    if (!archiveTarget) return;
    try {
      if (archiveTarget.is_archived) await complianceApi.unarchiveStandard(orgId, archiveTarget.id);
      else await complianceApi.archiveStandard(orgId, archiveTarget.id);
      showToast(archiveTarget.is_archived ? "Standard unarchived." : "Standard archived.");
      setArchiveTarget(null);
      setSelected(null);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update standard."), "error");
    }
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (standards === null) return <p>Loading…</p>;

  if (selected && activeVersion) {
    return (
      <VersionWorkspace
        orgId={orgId}
        standard={selected}
        version={activeVersion}
        versions={versions ?? []}
        actionTypes={actionTypes}
        onBack={() => setActiveVersion(null)}
        onVersionChanged={(updated) => {
          setActiveVersion(updated);
          setVersions((prev) => (prev ? prev.map((v) => (v.id === updated.id ? updated : v)) : prev));
        }}
      />
    );
  }

  const filtered = standards.filter(
    (s) => !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.reference.toLowerCase().includes(search.toLowerCase())
  );

  const columns: DirectoryColumn<ComplianceStandard>[] = [
    { key: "reference", label: "Reference", sortable: false, render: (s) => s.reference },
    { key: "name", label: "Name", sortable: false, render: (s) => s.name },
    { key: "issuing_organisation", label: "Issuing organisation", render: (s) => s.issuing_organisation ?? "—" },
    { key: "status", label: "Status", render: (s) => (s.is_archived ? "Archived" : "Active") },
  ];

  return (
    <div className="stack">
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New standard
      </button>
      <div className="side-grid">
        <FilterPanel sectionKey="compliance.standards" total={standards.length} matching={filtered.length} search={search} onSearchChange={setSearch} searchPlaceholder="Search standards…" searchAriaLabel="Search standards">
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={setIncludeArchived} />
        </FilterPanel>
        <DirectoryTable
          ariaLabel="Compliance standards"
          columns={columns}
          rows={filtered}
          rowKey={(s) => s.id}
          onRowClick={openStandard}
          emptyState={<p className="text-muted">No compliance standards yet.</p>}
        />
      </div>

      {creating && (
        <StandardFormModal
          onCancel={() => setCreating(false)}
          onSave={async (values) => {
            try {
              await complianceApi.createStandard(orgId, values);
              showToast("Standard created.");
              setCreating(false);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not create standard."), "error");
            }
          }}
        />
      )}

      {selected && !activeVersion && (
        <SidePanel title={`${selected.reference} — ${selected.name}`} onClose={() => setSelected(null)}>
          <div className="stack">
            <p>{selected.description || <span className="text-muted">No description.</span>}</p>
            {selected.issuing_organisation && <p className="text-muted">Issued by {selected.issuing_organisation}</p>}
            <div className="row">
              <button className="btn" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn btn-danger" onClick={() => setArchiveTarget(selected)}>
                {selected.is_archived ? "Unarchive" : "Archive"}
              </button>
            </div>

            <h3 style={{ margin: "0.5rem 0 0" }}>Versions</h3>
            {versions === null ? (
              <p>Loading…</p>
            ) : versions.length === 0 ? (
              <p className="text-muted">No versions yet.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {versions.map((v) => (
                  <li key={v.id} className="row" style={{ justifyContent: "space-between", padding: "0.35rem 0", borderBottom: "1px solid var(--color-border)" }}>
                    <button className="btn" onClick={() => setActiveVersion(v)}>
                      {v.version_label}
                    </button>
                    <span className="text-muted">{COMPLIANCE_STANDARD_VERSION_STATUS_LABEL[v.status]}</span>
                  </li>
                ))}
              </ul>
            )}
            <button className="btn" style={{ alignSelf: "flex-start" }} onClick={() => setCreatingVersion(true)}>
              New version
            </button>
          </div>
        </SidePanel>
      )}

      {editing && selected && (
        <StandardFormModal
          initial={selected}
          onCancel={() => setEditing(false)}
          onSave={async ({ name, description, issuing_organisation }) => {
            try {
              const updated = await complianceApi.updateStandard(orgId, selected.id, {
                name,
                description,
                issuing_organisation,
                owner_id: selected.owner_id,
              });
              showToast("Standard updated.");
              setEditing(false);
              setSelected(updated);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not update standard."), "error");
            }
          }}
        />
      )}

      {creatingVersion && selected && (
        <VersionFormModal
          versions={versions ?? []}
          onCancel={() => setCreatingVersion(false)}
          onSave={async (values) => {
            try {
              await complianceApi.createStandardVersion(orgId, selected.id, values);
              showToast("Version created.");
              setCreatingVersion(false);
              await reloadVersions(selected);
            } catch (err) {
              showToast(toErrorMessage(err, "Could not create version."), "error");
            }
          }}
        />
      )}

      {archiveTarget && (
        <ConfirmDialog
          title={archiveTarget.is_archived ? `Unarchive "${archiveTarget.name}"?` : `Archive "${archiveTarget.name}"?`}
          message={
            archiveTarget.is_archived
              ? "This standard will reappear in the default (non-archived) list."
              : "This standard will be hidden from the default list. Nothing referencing it is deleted."
          }
          confirmLabel={archiveTarget.is_archived ? "Unarchive" : "Archive"}
          onConfirm={handleArchiveToggle}
          onCancel={() => setArchiveTarget(null)}
        />
      )}
    </div>
  );
}

function StandardFormModal({
  initial,
  onCancel,
  onSave,
}: {
  initial?: ComplianceStandard;
  onCancel: () => void;
  onSave: (values: {
    reference: string;
    name: string;
    description: string;
    issuing_organisation: string | null;
    initial_version_label: string;
    initial_version_effective_date: string | null;
    initial_version_change_note: string;
  }) => void;
}) {
  const [reference, setReference] = useState(initial?.reference ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [issuingOrganisation, setIssuingOrganisation] = useState(initial?.issuing_organisation ?? "");
  const [versionLabel, setVersionLabel] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [changeNote, setChangeNote] = useState("");

  return (
    <Modal title={initial ? "Edit standard" : "New standard"} onClose={onCancel}>
      <div className="stack">
        {!initial && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Reference</span>
            <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. ISO-27001" aria-label="Standard reference" />
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
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!name.trim() || (!initial && (!reference.trim() || !versionLabel.trim()))}
            onClick={() =>
              onSave({
                reference,
                name,
                description,
                issuing_organisation: issuingOrganisation || null,
                initial_version_label: versionLabel,
                initial_version_effective_date: effectiveDate || null,
                initial_version_change_note: changeNote,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}

function VersionFormModal({
  versions,
  onCancel,
  onSave,
}: {
  versions: ComplianceStandardVersion[];
  onCancel: () => void;
  onSave: (values: { version_label: string; effective_date: string | null; change_note: string; clone_from_version_id: string | null }) => void;
}) {
  const [versionLabel, setVersionLabel] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [cloneFrom, setCloneFrom] = useState("");

  return (
    <Modal title="New version" onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Version label</span>
          <input className="input" value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} placeholder="e.g. v2.0" aria-label="Version label" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Effective date</span>
          <input className="input" type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Change note</span>
          <textarea className="input" value={changeNote} onChange={(e) => setChangeNote(e.target.value)} rows={2} />
        </label>
        {versions.length > 0 && (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Clone requirements from</span>
            <select className="input" value={cloneFrom} onChange={(e) => setCloneFrom(e.target.value)} aria-label="Clone requirements from">
              <option value="">Start empty</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>{v.version_label}</option>
              ))}
            </select>
          </label>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!versionLabel.trim()}
            onClick={() =>
              onSave({
                version_label: versionLabel,
                effective_date: effectiveDate || null,
                change_note: changeNote,
                clone_from_version_id: cloneFrom || null,
              })
            }
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
