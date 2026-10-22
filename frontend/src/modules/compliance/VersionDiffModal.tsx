/**
 * Module: modules/compliance/VersionDiffModal
 *
 * §27's version-diff viewer — fetches `GET .../diff/{other}` for
 * two versions of the same standard and renders its five categories
 * (added/removed/modified/replaced/re-mapped). Read-only: the actual
 * "migrate a project to this version" action is project-scoped
 * (`project_router.py::migrate_project_compliance_version`) and explicitly
 * out of the org-level scope — this is the "preview
 * before you commit" half only, per that endpoint's own docstring.
 */
import { useEffect, useState, type ReactNode } from "react";

import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceStandardVersion, StandardVersionDiff } from "./types";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useResetOnChange } from "../../hooks/useResetOnChange";

interface Props {
  orgId: string;
  standardId: string;
  fromVersionId: string;
  versions: ComplianceStandardVersion[];
  onClose: () => void;
}

export function VersionDiffModal({ orgId, standardId, fromVersionId, versions, onClose }: Props) {
  const otherVersions = versions.filter((v) => v.id !== fromVersionId);
  const [otherVersionId, setOtherVersionId] = useState(otherVersions[0]?.id ?? "");
  const [diff, setDiff] = useState<StandardVersionDiff | null>(null);
  const [error, setError] = useState<string | null>(null);

  useResetOnChange([orgId, standardId, fromVersionId, otherVersionId], () => {
    setDiff(null);
    setError(null);
  });

  useEffect(() => {
    if (!otherVersionId) return;
    complianceApi
      .getStandardVersionDiff(orgId, standardId, fromVersionId, otherVersionId)
      .then(setDiff)
      .catch((err) => setError(toErrorMessage(err, "Could not compute diff.")));
  }, [orgId, standardId, fromVersionId, otherVersionId]);

  function labelFor(versionId: string): string {
    return versions.find((v) => v.id === versionId)?.version_label ?? versionId;
  }

  return (
    <Modal title="Compare versions" onClose={onClose} size="lg">
      <div className="stack">
        <LabeledSelect helpNotNeeded
          label="Compare with"
          ariaLabel="Compare with version"
          value={otherVersionId}
          onChange={setOtherVersionId}
          options={otherVersions.map((v) => ({ value: v.id, label: v.version_label }))}
          placeholder="Select a version…"
        />

        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}

        {diff && (
          <div className="stack">
            <p className="text-muted" style={{ margin: 0 }}>
              Comparing {labelFor(diff.old_version_id)} (older) to {labelFor(diff.new_version_id)} (newer).
            </p>

            <DiffSection title={`Added (${diff.added.length})`}>
              {diff.added.map((row) => (
                <li key={row.requirement.id}>{row.requirement.reference ? `${row.requirement.reference} — ` : ""}{row.requirement.name}</li>
              ))}
            </DiffSection>

            <DiffSection title={`Removed (${diff.removed.length})`}>
              {diff.removed.map((row) => (
                <li key={row.requirement.id}>{row.requirement.reference ? `${row.requirement.reference} — ` : ""}{row.requirement.name}</li>
              ))}
            </DiffSection>

            <DiffSection title={`Modified (${diff.modified.length})`}>
              {diff.modified.map((row) => (
                <li key={row.new_requirement.id}>
                  {row.new_requirement.reference ? `${row.new_requirement.reference} — ` : ""}
                  {row.new_requirement.name}
                  <span className="text-muted"> (changed: {row.changed_fields.join(", ")})</span>
                </li>
              ))}
            </DiffSection>

            <DiffSection title={`Replaced (${diff.replaced.length})`}>
              {diff.replaced.map((row) => (
                <li key={row.mapping_id}>
                  {row.old_requirement.name} → {row.new_requirement.name}
                  <span className="text-muted">
                    {" "}
                    ({row.implies_equivalence ? "eligible for assessment carry-forward" : "not eligible for carry-forward"})
                  </span>
                </li>
              ))}
            </DiffSection>

            <DiffSection title={`Re-mapped (${diff.re_mapped.length})`}>
              {diff.re_mapped.map((row) => (
                <li key={row.new_requirement.id}>
                  {row.new_requirement.reference ? `${row.new_requirement.reference} — ` : ""}
                  {row.new_requirement.name}
                  <span className="text-muted"> — mapping links may need re-establishing</span>
                </li>
              ))}
            </DiffSection>
          </div>
        )}

        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </Modal>
  );
}

function DiffSection({ title, children }: { title: string; children: ReactNode }) {
  const isEmpty = Array.isArray(children) ? children.length === 0 : false;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <h4 style={{ margin: 0 }}>{title}</h4>
      {isEmpty ? <p className="text-muted" style={{ margin: 0 }}>None.</p> : <ul style={{ margin: 0 }}>{children}</ul>}
    </div>
  );
}
