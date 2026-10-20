/**
 * Module: modules/compliance/RequirementMappingsModal
 *
 * §19's cross-standard/cross-version requirement mapping UI, opened from one
 * requirement's own row in `RequirementTree.tsx` — lists that requirement's
 * existing mapping links (visible "from both requirements," per §19; this
 * view is one side of that) and lets a Compliance Manager add a new one by
 * picking a target requirement through three cascading selects (standard ->
 * version -> requirement), since there is no cross-org requirement search
 * endpoint to type-ahead against.
 */
import { useEffect, useState } from "react";

import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceMappingRelationshipType, ComplianceRequirement, ComplianceRequirementMapping, ComplianceStandard, ComplianceStandardVersion } from "./types";
import { TextField } from "../../components/FormFields";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useStrings } from "../../context/TerminologyContext";
import { COMPLIANCE_HELP } from "./help";

interface Props {
  orgId: string;
  standardId: string;
  versionId: string;
  requirement: ComplianceRequirement;
  onClose: () => void;
}

export function RequirementMappingsModal({ orgId, standardId, versionId, requirement, onClose }: Props) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [mappings, setMappings] = useState<ComplianceRequirementMapping[] | null>(null);
  const [relationshipTypes, setRelationshipTypes] = useState<ComplianceMappingRelationshipType[]>([]);
  const [standards, setStandards] = useState<ComplianceStandard[]>([]);

  const [targetStandardId, setTargetStandardId] = useState("");
  const [targetVersions, setTargetVersions] = useState<ComplianceStandardVersion[]>([]);
  const [targetVersionId, setTargetVersionId] = useState("");
  const [targetRequirements, setTargetRequirements] = useState<ComplianceRequirement[]>([]);
  const [targetRequirementId, setTargetRequirementId] = useState("");
  const [relationshipTypeId, setRelationshipTypeId] = useState("");
  const [notes, setNotes] = useState("");

  async function reload() {
    try {
      setMappings(await complianceApi.listMappingsForRequirement(orgId, standardId, versionId, requirement.id));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not load mappings."), "error");
    }
  }

  useLoadOnChange(() => {
    void reload();
    void complianceApi.listMappingRelationshipTypes(orgId).then(setRelationshipTypes);
    void complianceApi.listStandards(orgId).then(setStandards);
  }, [orgId, standardId, versionId, requirement.id]);

  useResetOnChange([orgId, targetStandardId], () => {
    setTargetVersionId("");
    setTargetVersions([]);
    setTargetRequirements([]);
    setTargetRequirementId("");
  });

  useEffect(() => {
    if (!targetStandardId) return;
    void complianceApi.listStandardVersions(orgId, targetStandardId).then(setTargetVersions);
  }, [orgId, targetStandardId]);

  useResetOnChange([orgId, targetStandardId, targetVersionId], () => {
    setTargetRequirements([]);
    setTargetRequirementId("");
  });

  useEffect(() => {
    if (!targetStandardId || !targetVersionId) return;
    void complianceApi.listRequirements(orgId, targetStandardId, targetVersionId).then(setTargetRequirements);
  }, [orgId, targetStandardId, targetVersionId]);

  async function handleCreate() {
    if (!targetRequirementId || !relationshipTypeId) return;
    try {
      await complianceApi.createRequirementMapping(orgId, {
        from_requirement_id: requirement.id,
        to_requirement_id: targetRequirementId,
        relationship_type_id: relationshipTypeId,
        notes,
      });
      showToast("Mapping created.");
      setTargetStandardId("");
      setNotes("");
      setRelationshipTypeId("");
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not create mapping."), "error");
    }
  }

  async function handleArchiveToggle(mapping: ComplianceRequirementMapping) {
    try {
      if (mapping.is_archived) await complianceApi.unarchiveRequirementMapping(orgId, mapping.id);
      else await complianceApi.archiveRequirementMapping(orgId, mapping.id);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update mapping."), "error");
    }
  }

  function otherSideId(mapping: ComplianceRequirementMapping): string {
    return mapping.from_requirement_id === requirement.id ? mapping.to_requirement_id : mapping.from_requirement_id;
  }

  function relationshipTypeName(id: string): string {
    return relationshipTypes.find((t) => t.id === id)?.name ?? "—";
  }

  return (
    <Modal title={`Mappings for "${requirement.name}"`} onClose={onClose} size="lg">
      <div className="stack">
        {mappings === null ? (
          <p>Loading…</p>
        ) : mappings.length === 0 ? (
          <p className="text-muted">No mappings yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Relationship</th>
                <th>Other requirement id</th>
                <th>Notes</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((m) => (
                <tr key={m.id} style={m.is_archived ? { opacity: 0.55 } : undefined}>
                  <td>{relationshipTypeName(m.relationship_type_id)}</td>
                  <td className="text-muted" style={{ fontSize: "0.8rem" }}>{otherSideId(m)}</td>
                  <td>{m.notes}</td>
                  <td>
                    <button className="btn" onClick={() => handleArchiveToggle(m)}>
                      {m.is_archived ? "Unarchive" : "Archive"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3 style={{ margin: "0.5rem 0 0" }}>Add mapping</h3>
        <div className="row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          <LabeledSelect helpNotNeeded
            label="Target standard"
            value={targetStandardId}
            onChange={setTargetStandardId}
            options={standards.map((s) => ({ value: s.id, label: `${s.reference} — ${s.name}` }))}
          />
          <LabeledSelect help={strings.help.requirementTargetVersion}
            label="Target version"
            value={targetVersionId}
            onChange={setTargetVersionId}
            options={targetVersions.map((v) => ({ value: v.id, label: v.version_label }))}
            disabled={!targetStandardId}
          />
          <LabeledSelect helpNotNeeded
            label="Target requirement"
            value={targetRequirementId}
            onChange={setTargetRequirementId}
            options={targetRequirements
              .filter((r) => r.id !== requirement.id)
              .map((r) => ({ value: r.id, label: `${r.reference ? `${r.reference} — ` : ""}${r.name}` }))}
            disabled={!targetVersionId}
          />
          <LabeledSelect help={COMPLIANCE_HELP.complianceMappingRelationship}
            label="Relationship type"
            value={relationshipTypeId}
            onChange={setRelationshipTypeId}
            options={relationshipTypes.map((t) => ({ value: t.id, label: t.name }))}
          />
        </div>
        <TextField helpNotNeeded label="Notes" value={notes} onChange={setNotes} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Close</button>
          <button className="btn btn-primary" disabled={!targetRequirementId || !relationshipTypeId} onClick={handleCreate}>
            Add mapping
          </button>
        </div>
      </div>
    </Modal>
  );
}
