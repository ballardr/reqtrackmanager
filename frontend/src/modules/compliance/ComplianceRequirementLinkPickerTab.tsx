/**
 * Module: modules/compliance/ComplianceRequirementLinkPickerTab
 *
 * The Compliance module's contribution to the shared
 * `RequirementLinkPickerModal` (`components/RequirementLinkPickerModal.tsx`,
 * platform-review-2026-09 Phase 7), via the new `requirementLinkPickerTabs`
 * extension point (`modules/types.ts`) — lets a user pick a target
 * `ComplianceRequirement` through three cascading selects (standard ->
 * version -> requirement, the same `RequirementMappingsModal.tsx` precedent:
 * there is no cross-org compliance-requirement search endpoint to type-ahead
 * against) plus a core `RequirementLinkTypeDefinition` select (the same
 * org-scoped vocabulary core's own requirement-to-requirement links use),
 * then creates the link directly via `complianceApi.
 * createRequirementTraceabilityLink` — this module owns its own mutation
 * (Modular Feature System Boundary; core never calls a module's API on its
 * behalf) and reports success via `onLinked()`.
 *
 * Extracted from `RequirementTraceabilityLinksSection.tsx`'s old inline
 * "Add compliance link" `Popover`, which owned this exact form until this
 * phase moved link-creation into the shared picker modal, leaving that
 * component with only the existing-links list.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { LinkTypeDefinition } from "../../api/types";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceRequirement, ComplianceStandard, ComplianceStandardVersion } from "./types";

interface Props {
  projectId: string;
  requirementId: string;
  organizationId: string;
  onLinked: () => void;
}

export function ComplianceRequirementLinkPickerTab({ projectId, requirementId, organizationId, onLinked }: Props) {
  const strings = useStrings();
  const [linkTypes, setLinkTypes] = useState<LinkTypeDefinition[]>([]);
  const [standards, setStandards] = useState<ComplianceStandard[]>([]);

  const [targetStandardId, setTargetStandardId] = useState("");
  const [targetVersions, setTargetVersions] = useState<ComplianceStandardVersion[]>([]);
  const [targetVersionId, setTargetVersionId] = useState("");
  const [targetRequirements, setTargetRequirements] = useState<ComplianceRequirement[]>([]);
  const [targetRequirementId, setTargetRequirementId] = useState("");
  const [linkTypeId, setLinkTypeId] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.get<LinkTypeDefinition[]>(`/api/v1/orgs/${organizationId}/link-types`).then(setLinkTypes);
    void complianceApi.listStandards(organizationId).then(setStandards);
  }, [organizationId]);

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

  async function addLink() {
    if (!targetRequirementId || !linkTypeId) return;
    setError(null);
    try {
      await complianceApi.createRequirementTraceabilityLink(projectId, requirementId, {
        compliance_requirement_id: targetRequirementId,
        link_type_id: linkTypeId,
      });
      onLinked();
    } catch (err) {
      setError(toErrorMessage(err, strings.compliance.couldNotCreateLink));
    }
  }

  return (
    <div className="stack">
      <LabeledSelect
        label={strings.compliance.standard}
        value={targetStandardId}
        onChange={setTargetStandardId}
        options={standards.map((s) => ({ value: s.id, label: `${s.reference} — ${s.name}` }))}
      />
      <LabeledSelect
        label={strings.compliance.version}
        value={targetVersionId}
        onChange={setTargetVersionId}
        options={targetVersions.map((v) => ({ value: v.id, label: v.version_label }))}
        disabled={!targetStandardId}
      />
      <LabeledSelect
        label={strings.compliance.targetRequirement}
        value={targetRequirementId}
        onChange={setTargetRequirementId}
        options={targetRequirements.map((r) => ({
          value: r.id,
          label: `${r.reference ? `${r.reference} — ` : ""}${r.name}`,
        }))}
        disabled={!targetVersionId}
      />
      <LabeledSelect
        label={strings.requirements.linkType}
        value={linkTypeId}
        onChange={setLinkTypeId}
        options={linkTypes.map((lt) => ({ value: lt.id, label: lt.forward_name }))}
      />
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn btn-primary" disabled={!targetRequirementId || !linkTypeId} onClick={addLink}>
          {strings.requirements.addLink}
        </button>
      </div>
    </div>
  );
}
