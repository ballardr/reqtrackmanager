/**
 * Module: modules/compliance/ApplicabilityTree
 *
 * The requirement-hierarchy assessment workspace for one project's
 * standard assignment (§8-§10, §16) — a client-side-assembled tree (same
 * `buildRequirementTree` algorithm `RequirementTree.tsx`/Phase 12 already
 * proved out) over the standard version's requirement definitions, each
 * node decorated with this project's own `ProjectComplianceRequirement`
 * assessment row.
 *
 * §9's own explicit, non-optional UI requirement — "The UI must clearly
 * distinguish: Explicitly set applicability, Applicability inherited from
 * a parent, An overridden inherited value" — is carried by
 * `ApplicabilityBadge` below: EXPLICIT renders as a plain, undecorated
 * badge (this is the ordinary case — a user decision, or nothing decided
 * and no ancestor says otherwise, both of which render identically per
 * `ComplianceApplicabilitySource`'s own docstring), INHERITED renders
 * greyed/italic with an explanatory `title`, and OVERRIDDEN renders in the
 * warning colour with its own explanatory `title` — three genuinely
 * distinct visual treatments, not just three label strings, so the
 * distinction survives a quick scan of the tree, not just a hover.
 *
 * Selecting a row opens `RequirementAssessmentPanel` (a `SidePanel` — style
 * guide "Pattern: entity detail panel," viewing an existing entity's detail
 * without leaving the tree behind it) for the actual applicability/
 * assessment/required-actions/evidence/approval workflow; this component
 * owns only the tree's read/navigation concern.
 */
import { useEffect, useState } from "react";

import { COMPLIANCE_APPROVAL_STATE_LABEL, COMPLIANCE_STATUS_LABEL, type OrgUser } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { ApplicabilityBadge } from "./ApplicabilityBadge";
import * as complianceApi from "./api";
import { RequirementAssessmentPanel } from "./RequirementAssessmentPanel";
import type { ComplianceRequirementNode, ProjectComplianceRequirement } from "./types";

interface Props {
  orgId: string;
  projectId: string;
  standardId: string;
  versionId: string;
  projectComplianceId: string;
  orgUsers: OrgUser[];
  /** Called after any requirement change (applicability, assessment,
   * approval decision) settles — `ProjectComplianceDetail` uses this to
   * refresh its own §20 overall-status summary card, which otherwise stays
   * on the snapshot fetched when the assignment list first loaded (found
   * while verifying this phase end to end: assessing/approving a
   * requirement left the "Overall compliance status" card showing stale
   * counts until the assignment was closed and reopened). */
  onAssessmentChanged?: () => void;
}

export function ApplicabilityTree({
  orgId, projectId, standardId, versionId, projectComplianceId, orgUsers, onAssessmentChanged,
}: Props) {
  const { showToast } = useToast();
  const [tree, setTree] = useState<ComplianceRequirementNode[] | null>(null);
  const [pcrByRequirementId, setPcrByRequirementId] = useState<Record<string, ProjectComplianceRequirement>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedPcrId, setSelectedPcrId] = useState<string | null>(null);

  async function reload() {
    try {
      const [requirements, pcrs] = await Promise.all([
        complianceApi.listRequirements(orgId, standardId, versionId),
        complianceApi.listProjectComplianceRequirements(projectId, projectComplianceId),
      ]);
      setTree(complianceApi.buildRequirementTree(requirements));
      setPcrByRequirementId(Object.fromEntries(pcrs.map((pcr) => [pcr.requirement_id, pcr])));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load this assignment's requirements."));
    }
  }

  useEffect(() => {
    setTree(null);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, standardId, versionId, projectComplianceId]);

  async function reloadOne(pcrId: string) {
    // Re-fetches every pcr rather than just one, since a change (e.g.
    // applicability) can cascade to descendants' *effective* applicability —
    // resolved server-side across the whole assignment, not just the edited
    // row (`service.py::resolve_applicability`). The list is small enough
    // per assignment that this is cheap.
    try {
      const pcrs = await complianceApi.listProjectComplianceRequirements(projectId, projectComplianceId);
      setPcrByRequirementId(Object.fromEntries(pcrs.map((pcr) => [pcr.requirement_id, pcr])));
      onAssessmentChanged?.();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not refresh requirements."), "error");
    }
    void pcrId; // kept for call-site clarity; the reload itself is always a full refetch
  }

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (tree === null) return <Spinner />;

  const selectedPcr = selectedPcrId
    ? Object.values(pcrByRequirementId).find((pcr) => pcr.id === selectedPcrId) ?? null
    : null;
  const selectedRequirement = selectedPcr
    ? findRequirement(tree, selectedPcr.requirement_id)
    : null;

  function renderNode(node: ComplianceRequirementNode) {
    const pcr = pcrByRequirementId[node.id];
    return (
      <li key={node.id} style={{ marginLeft: node.depth === 0 ? 0 : "1.25rem" }}>
        <button
          type="button"
          className="card"
          style={{ width: "100%", textAlign: "left", padding: "0.5rem 0.75rem", marginBottom: "0.4rem", cursor: "pointer" }}
          onClick={() => pcr && setSelectedPcrId(pcr.id)}
          disabled={!pcr}
        >
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.4rem" }}>
            <span>
              {node.reference && <span className="text-muted">{node.reference} — </span>}
              <strong>{node.name}</strong>
            </span>
            {pcr && (
              <div className="row" style={{ flexWrap: "wrap", gap: "0.3rem" }}>
                <ApplicabilityBadge pcr={pcr} />
                {pcr.effective_applicability === "applicable" && (
                  <span className="badge">{COMPLIANCE_STATUS_LABEL[pcr.compliance_status]}</span>
                )}
                {pcr.approval_state !== "not_assessed" && (
                  <span className="badge">{COMPLIANCE_APPROVAL_STATE_LABEL[pcr.approval_state]}</span>
                )}
              </div>
            )}
          </div>
        </button>
        {node.children.length > 0 && (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>{node.children.map(renderNode)}</ul>
        )}
      </li>
    );
  }

  return (
    <div className="stack">
      {tree.length === 0 ? (
        <p className="text-muted">This standard version has no requirements defined.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>{tree.map(renderNode)}</ul>
      )}

      {selectedPcr && selectedRequirement && (
        <RequirementAssessmentPanel
          orgId={orgId}
          projectId={projectId}
          standardId={standardId}
          versionId={versionId}
          projectComplianceId={projectComplianceId}
          requirement={selectedRequirement}
          pcr={selectedPcr}
          orgUsers={orgUsers}
          onClose={() => setSelectedPcrId(null)}
          onChanged={() => reloadOne(selectedPcr.id)}
        />
      )}
    </div>
  );
}

function findRequirement(tree: ComplianceRequirementNode[], requirementId: string): ComplianceRequirementNode | null {
  for (const node of tree) {
    if (node.id === requirementId) return node;
    const found = findRequirement(node.children, requirementId);
    if (found) return found;
  }
  return null;
}
