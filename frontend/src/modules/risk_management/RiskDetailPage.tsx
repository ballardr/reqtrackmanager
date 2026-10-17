/**
 * Module: modules/risk_management/RiskDetailPage
 *
 * A single risk's full detail as a routed page (`/projects/:projectId/modules/
 * risk_management/risks/:riskId`, `module.ts`; the path `module.ts` also
 * declares for `artefactPaths`). A risk carries a lifecycle with
 * a dialog per move, treatment verdicts, a review history, version history,
 * attachments, comments and a Links panel, so it is a page rather than a
 * `SidePanel` (docs/ux-style-guide.md "Pattern: entity detail panel").
 *
 * The page fetches its own data. Edit is a Modal layer that sends only changed
 * fields (a new version). The matrix shows where the risk sits, inherent and
 * residual, on the project's configured grid. The Links panel makes the
 * relationships (Mitigated by, Treated by, Verified by, ...); `RiskTreatmentsPanel`
 * then records whether each treatment actually works. Every mutating control
 * always renders regardless of role; the backend enforces Risk Manager / Risk
 * Acceptor and a 403 surfaces as a toast or in the dialog.
 */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import type { OrgUser, Project } from "../../api/types";
import { ArtefactLinksPanel } from "../../components/ArtefactLinksPanel";
import { DetailLayout } from "../../components/DetailLayout";
import { RecordDiscussion } from "../../components/RecordDiscussion";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordField, RecordFieldGroup, VersionHistoryTable } from "../../components/RecordDetailParts";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { riskApi } from "./api";
import { diffRiskFields, valuesFromRisk } from "./riskFields";
import { RiskFormModal } from "./RiskFormModal";
import { RiskLifecycleControls } from "./RiskLifecycleControls";
import { RiskMatrix } from "./RiskMatrix";
import { RiskRatingBadge } from "./RiskRatingBadge";
import { RiskReviewsPanel } from "./RiskReviewsPanel";
import { RiskTreatmentsPanel } from "./RiskTreatmentsPanel";
import {
  CONSEQUENCE_AXIS, DETECTABILITY_AXIS, levelName, LIKELIHOOD_AXIS, useRiskScheme,
} from "./useRiskScheme";
import { RISK_STATUS_LABEL, RISK_STATUS_TONE, TREATMENT_STRATEGY_LABEL } from "./types";
import type { Risk, RiskFieldValues, RiskStatus, RiskVersion } from "./types";

/** "Likely × Major" (and "× Undetectable" when scored), or "—" when nothing is set. */
function levelSummary(
  scheme: ReturnType<typeof useRiskScheme>, likelihood: string | null, consequence: string | null, detectability: string | null,
): string {
  const parts = [
    levelName(scheme, LIKELIHOOD_AXIS, likelihood),
    levelName(scheme, CONSEQUENCE_AXIS, consequence),
    ...(detectability ? [levelName(scheme, DETECTABILITY_AXIS, detectability)] : []),
  ];
  return parts.every((p) => p === "—") ? "—" : parts.join(" × ");
}

export function RiskDetailPage() {
  const { projectId, riskId } = useParams<{ projectId: string; riskId: string }>();
  const { user } = useAuth();
  const { showToast } = useToast();
  const scheme = useRiskScheme(projectId);

  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [riskTypes, setRiskTypes] = useState<{ id: string; name: string }[]>([]);
  const [risk, setRisk] = useState<Risk | null>(null);
  const [versions, setVersions] = useState<RiskVersion[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [treatmentsRefresh, setTreatmentsRefresh] = useState(0);

  useEffect(() => {
    if (!projectId || !riskId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((proj) => {
      setProject(proj);
      api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`).then(setOrgUsers).catch(() => setOrgUsers([]));
    });
    riskApi
      .listTypes(projectId)
      .then((types) => setRiskTypes(types.filter((t) => t.is_enabled).map((t) => ({ id: t.id, name: t.name }))))
      .catch(() => setRiskTypes([]));
    riskApi.get(projectId, riskId).then(setRisk).catch((err) => {
      setLoadError(toErrorMessage(err, "This Risk could not be found, or you don't have access to it."));
    });
  }, [projectId, riskId]);

  const version = risk?.version_number;
  useEffect(() => {
    if (!projectId || !riskId || version === undefined) return;
    let active = true;
    riskApi.listVersions(projectId, riskId).then((list) => active && setVersions(list)).catch(() => active && setVersions([]));
    return () => {
      active = false;
    };
  }, [projectId, riskId, version]);

  /** Reloads the risk (its derived fields move when treatments, reviews or links change). */
  async function reloadRisk() {
    if (!projectId || !riskId) return;
    try {
      setRisk(await riskApi.get(projectId, riskId));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not refresh this Risk."), "error");
    }
  }

  async function saveEdit(values: RiskFieldValues, changeNote: string) {
    if (!projectId || !risk) return;
    setFormError(null);
    const changed = diffRiskFields(valuesFromRisk(risk), values);
    if (Object.keys(changed).length === 0) {
      showToast("Nothing changed.");
      setEditing(false);
      return;
    }
    try {
      const updated = await riskApi.update(projectId, risk.id, { ...changed, change_note: changeNote });
      showToast("Risk updated.");
      setEditing(false);
      setRisk(updated);
    } catch (err) {
      setFormError(toErrorMessage(err, "Could not update this Risk."));
    }
  }

  if (!projectId || !riskId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (risk === null || project === null) return <Spinner />;

  const userNames = Object.fromEntries(orgUsers.map((u) => [u.user_id, u.display_name]));

  return (
    <DetailLayout
      aside={
        <ArtefactLinksPanel
          projectId={projectId}
          artefactType="risk"
          artefactId={risk.id}
          onChanged={() => {
            setTreatmentsRefresh((n) => n + 1);
            void reloadRisk();
          }}
        />
      }
    >
      <Link to={`/projects/${projectId}/modules/risk_management/risks`}>← Risks</Link>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>{risk.unique_code}</h1>
        <span className="row" style={{ gap: "0.5rem" }}>
          {risk.is_review_overdue && <span className="badge badge--danger">Review overdue</span>}
          {risk.is_archived && <span className="badge badge--muted">Archived</span>}
          <span className={`badge badge--${RISK_STATUS_TONE[risk.status]}`}>{RISK_STATUS_LABEL[risk.status]}</span>
        </span>
      </div>
      <div className="stack">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>{risk.title}</h2>
          {!risk.is_archived && (
            <button className="btn btn-icon" title="Edit" aria-label="Edit" onClick={() => setEditing(true)}>
              <Pencil size={14} />
            </button>
          )}
        </div>
        <p className="text-muted" style={{ margin: 0 }}>
          {risk.risk_type_name ?? "No type"} · Owner: <PrincipalBadge principal={risk.owner} /> ·{" "}
          {risk.treatment_strategy ? `Strategy: ${TREATMENT_STRATEGY_LABEL[risk.treatment_strategy]}` : "No treatment strategy"}
        </p>
        {risk.statement && <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{risk.statement}</p>}
        {risk.cause && <RecordField label="Cause" value={risk.cause} />}
        {risk.risk_event && <RecordField label="Risk event" value={risk.risk_event} />}
        {risk.consequence && <RecordField label="Consequence" value={risk.consequence} />}
        {risk.acceptance_criteria && <RecordField label="Acceptance criteria" value={risk.acceptance_criteria} />}

        <section className="stack" aria-label="Rating" style={{ borderTop: "1px solid var(--color-border)", paddingTop: "0.75rem" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Rating</h3>
          <div className="row" style={{ gap: "2rem", flexWrap: "wrap" }}>
            <RecordFieldGroup label="Inherent">
              <RiskRatingBadge rating={risk.inherent_rating} />
              <span className="text-muted">
                {levelSummary(scheme, risk.inherent_likelihood_level_id, risk.inherent_consequence_level_id, risk.inherent_detectability_level_id)}
              </span>
            </RecordFieldGroup>
            <RecordFieldGroup label="Residual">
              <RiskRatingBadge rating={risk.residual_rating} />
              <span className="text-muted">
                {levelSummary(scheme, risk.residual_likelihood_level_id, risk.residual_consequence_level_id, risk.residual_detectability_level_id)}
              </span>
            </RecordFieldGroup>
            <RecordFieldGroup label="Treatment">
              <span className={`badge badge--${risk.is_effectively_treated ? "accent" : "muted"}`}>
                {risk.is_effectively_treated ? `${risk.effective_treatment_count} effective` : "No effective treatment"}
              </span>
            </RecordFieldGroup>
          </div>
          <RiskMatrix scheme={scheme} risks={[risk]} basis="both" />
        </section>

        <RiskLifecycleControls
          risk={risk}
          onTransition={async (status: RiskStatus, comment: string) => {
            setRisk(await riskApi.transition(projectId, risk.id, status, comment));
            showToast(`Risk moved to ${RISK_STATUS_LABEL[status]}.`);
          }}
          onArchiveToggle={async () => {
            try {
              setRisk(await (risk.is_archived ? riskApi.unarchive(projectId, risk.id) : riskApi.archive(projectId, risk.id)));
              showToast(risk.is_archived ? "Risk unarchived." : "Risk archived.");
            } catch (err) {
              showToast(toErrorMessage(err, "Could not update this Risk."), "error");
            }
          }}
        />

        <RiskTreatmentsPanel projectId={projectId} riskId={risk.id} refreshToken={treatmentsRefresh} onChanged={reloadRisk} />
        <RiskReviewsPanel risk={risk} scheme={scheme} userNames={userNames} onRecorded={reloadRisk} />

        <VersionHistoryTable<RiskVersion>
          versions={versions}
          columns={[
            { header: "Status", render: (v) => RISK_STATUS_LABEL[v.status] },
            { header: "Owner", render: (v) => <PrincipalBadge principal={v.owner} /> },
            { header: "Inherent", render: (v) => levelSummary(scheme, v.inherent_likelihood_level_id, v.inherent_consequence_level_id, v.inherent_detectability_level_id) },
            { header: "Residual", render: (v) => levelSummary(scheme, v.residual_likelihood_level_id, v.residual_consequence_level_id, v.residual_detectability_level_id) },
          ]}
        />

        <RecordDiscussion
          api={riskApi}
          scopeId={projectId}
          recordId={risk.id}
          noun="Risk"
          currentUserId={user?.id}
          attachmentsReadOnly={risk.is_archived}
          attachmentsHint="This Risk is archived; new attachments can no longer be added."
        />
      </div>

      {editing && (
        <RiskFormModal
          initial={risk}
          scheme={scheme}
          riskTypes={riskTypes}
          orgUsers={orgUsers}
          organizationId={project.organization_id}
          projectId={projectId}
          currentUserId={user?.id}
          error={formError}
          onCancel={() => { setEditing(false); setFormError(null); }}
          onSave={saveEdit}
        />
      )}
    </DetailLayout>
  );
}
