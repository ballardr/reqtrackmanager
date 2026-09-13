/**
 * Module: modules/compliance/RequirementTraceabilityLinksSection
 *
 * The Compliance module's contribution to `pages/RequirementDetailPage
 * .tsx`'s own "Links" card (compliance-module-plan.md Phase 34), via the
 * `requirementDetailSections` extension point (`modules/types.ts`) — lists
 * this core requirement's own links to compliance standard requirements
 * and lets a user add one by picking a target through three cascading
 * selects (standard -> version -> requirement), the same
 * `RequirementMappingsModal.tsx` precedent (there is no cross-org
 * compliance-requirement search endpoint to type-ahead against), plus a
 * core `RequirementLinkTypeDefinition` select (`GET /orgs/{id}/link-types`
 * — the same org-scoped vocabulary core's own requirement-to-requirement
 * links use).
 *
 * V1 scope (Phase 34's own note): this is the *only* direction this phase
 * ships — initiating a link from a compliance standard's own requirement
 * browser is deliberately deferred, not built here.
 */
import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";

import { api } from "../../api/client";
import type { LinkTypeDefinition } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Popover } from "../../components/Popover";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type {
  ComplianceRequirement,
  ComplianceRequirementTraceabilityLink,
  ComplianceStandard,
  ComplianceStandardVersion,
} from "./types";

interface Props {
  projectId: string;
  requirementId: string;
  organizationId: string;
}

export function RequirementTraceabilityLinksSection({ projectId, requirementId, organizationId }: Props) {
  const { showToast } = useToast();
  const [links, setLinks] = useState<ComplianceRequirementTraceabilityLink[]>([]);
  const [linkTypes, setLinkTypes] = useState<LinkTypeDefinition[]>([]);
  const [standards, setStandards] = useState<ComplianceStandard[]>([]);

  const [popoverOpen, setPopoverOpen] = useState(false);
  const addTriggerRef = useRef<HTMLButtonElement>(null);
  const [targetStandardId, setTargetStandardId] = useState("");
  const [targetVersions, setTargetVersions] = useState<ComplianceStandardVersion[]>([]);
  const [targetVersionId, setTargetVersionId] = useState("");
  const [targetRequirements, setTargetRequirements] = useState<ComplianceRequirement[]>([]);
  const [targetRequirementId, setTargetRequirementId] = useState("");
  const [linkTypeId, setLinkTypeId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [linkToRemove, setLinkToRemove] = useState<ComplianceRequirementTraceabilityLink | null>(null);

  async function reload() {
    try {
      setLinks(await complianceApi.listRequirementTraceabilityLinks(projectId, requirementId));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load compliance requirement links."), "error");
    }
  }

  useEffect(() => {
    void reload();
    void api.get<LinkTypeDefinition[]>(`/api/v1/orgs/${organizationId}/link-types`).then(setLinkTypes);
    void complianceApi.listStandards(organizationId).then(setStandards);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, requirementId, organizationId]);

  useEffect(() => {
    setTargetVersionId("");
    setTargetVersions([]);
    setTargetRequirements([]);
    setTargetRequirementId("");
    if (!targetStandardId) return;
    void complianceApi.listStandardVersions(organizationId, targetStandardId).then(setTargetVersions);
  }, [organizationId, targetStandardId]);

  useEffect(() => {
    setTargetRequirements([]);
    setTargetRequirementId("");
    if (!targetStandardId || !targetVersionId) return;
    void complianceApi.listRequirements(organizationId, targetStandardId, targetVersionId).then(setTargetRequirements);
  }, [organizationId, targetStandardId, targetVersionId]);

  function resetForm() {
    setTargetStandardId("");
    setLinkTypeId("");
    setError(null);
  }

  async function addLink() {
    if (!targetRequirementId || !linkTypeId) return;
    try {
      await complianceApi.createRequirementTraceabilityLink(projectId, requirementId, {
        compliance_requirement_id: targetRequirementId, link_type_id: linkTypeId,
      });
      resetForm();
      setPopoverOpen(false);
      await reload();
    } catch (err) {
      setError(toErrorMessage(err, "Could not create link."));
    }
  }

  async function removeLink(linkId: string) {
    await complianceApi.deleteRequirementTraceabilityLink(projectId, requirementId, linkId);
    await reload();
  }

  return (
    <div className="stack" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem", marginTop: "0.25rem" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Compliance requirement links</h3>
        <button
          ref={addTriggerRef}
          className="btn"
          onClick={() => {
            setError(null);
            setPopoverOpen((o) => !o);
          }}
        >
          Add compliance link
        </button>
        {popoverOpen && (
          <Popover anchorRef={addTriggerRef} title="Add compliance link" onClose={() => setPopoverOpen(false)}>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Standard</span>
              <select
                className="input" aria-label="Standard"
                value={targetStandardId} onChange={(e) => setTargetStandardId(e.target.value)}
              >
                <option value="">Select…</option>
                {standards.map((s) => (
                  <option key={s.id} value={s.id}>{s.reference} — {s.name}</option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Version</span>
              <select
                className="input" aria-label="Version" disabled={!targetStandardId}
                value={targetVersionId} onChange={(e) => setTargetVersionId(e.target.value)}
              >
                <option value="">Select…</option>
                {targetVersions.map((v) => (
                  <option key={v.id} value={v.id}>{v.version_label}</option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Requirement</span>
              <select
                className="input" aria-label="Requirement" disabled={!targetVersionId}
                value={targetRequirementId} onChange={(e) => setTargetRequirementId(e.target.value)}
              >
                <option value="">Select…</option>
                {targetRequirements.map((r) => (
                  <option key={r.id} value={r.id}>{r.reference ? `${r.reference} — ` : ""}{r.name}</option>
                ))}
              </select>
            </label>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Link type</span>
              <select
                className="input" aria-label="Link type"
                value={linkTypeId} onChange={(e) => setLinkTypeId(e.target.value)}
              >
                <option value="">Select…</option>
                {linkTypes.map((lt) => (
                  <option key={lt.id} value={lt.id}>{lt.forward_name}</option>
                ))}
              </select>
            </label>
            {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setPopoverOpen(false)}>Cancel</button>
              <button className="btn btn-primary" disabled={!targetRequirementId || !linkTypeId} onClick={addLink}>
                Add link
              </button>
            </div>
          </Popover>
        )}
      </div>
      {links.length === 0 && <p className="text-muted" style={{ margin: 0 }}>No compliance requirement links yet.</p>}
      {links.map((link) => (
        <div key={link.id} className="row" style={{ justifyContent: "space-between" }}>
          <span>
            <span className="badge">{link.display_name}</span>{" "}
            {link.standard_reference} — {link.compliance_requirement_reference ? `${link.compliance_requirement_reference} ` : ""}
            {link.compliance_requirement_name}
            <span className="text-muted"> ({link.standard_name}, v{link.standard_version_label})</span>
          </span>
          <button
            className="btn btn-danger"
            title="Remove link"
            aria-label="Remove link"
            onClick={() => setLinkToRemove(link)}
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {linkToRemove && (
        <ConfirmDialog
          title="Remove compliance link"
          message="Remove this traceability link? This does not affect either requirement's own content."
          confirmLabel="Remove link"
          onConfirm={async () => {
            const id = linkToRemove.id;
            setLinkToRemove(null);
            await removeLink(id);
          }}
          onCancel={() => setLinkToRemove(null)}
        />
      )}
    </div>
  );
}
