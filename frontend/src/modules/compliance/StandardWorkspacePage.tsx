/**
 * Module: modules/compliance/StandardWorkspacePage
 *
 * The per-standard workspace at `/standards/:standardId[/versions|/history]`, opened from a row of `StandardListPage.tsx`. It is
 * a sibling of a project's workspace (`Layout.tsx`'s "Standard" nav-rail section, rendered while a `standardId` is in the URL):
 * Overview/Details, Versions (`StandardVersionsSection` reusing `VersionWorkspace`) and History.
 * - The URL has no organisation id, so the page resolves it through `GET /api/v1/compliance/standards/{standard_id}`
 *   (`global_router.py`) and threads `organization_id` to the organisation-scoped calls (versions, requirements, history, action types).
 * - Sections use a real route (`:section?`, default "overview"), as `ProjectAdminPage.tsx`'s `:group?`, expressed as `NavRailLink`s
 *   because a Standard is a project-like entity, not a fixed set of settings screens (docs/ux-style-guide.md, "Pattern: project-like
 *   drill-down entities"; `ComplianceSettingsPage.tsx` uses a `ResourceMenu` for those).
 * - `StandardApplicabilityPanel` (the "applies to all projects by default, except..." toggle and exclusions, Compliance-Manager-only)
 *   is in Overview. A Project Manager's self-service assignment lives on `ProjectCompliancePage.tsx`, being project-scoped.
 * - "Export" sits with Archive in the record header menu and downloads the standard's portable JSON (`complianceApi.exportStandard`
 *   + `downloadBlob`) for backup or transfer through `StandardListPage.tsx`'s "Import standard".
 * - The Overview `.grid.grid-metrics` row of `MetricTile`s (versions, requirements, projects, compliant) links into a `"projects"`
 *   section (`StandardProjectsPanel.tsx`); an optional `versionId` route param reaches `StandardVersionsSection`/`VersionWorkspace`,
 *   so `StandardNavSection.tsx`'s Versions group and the "Requirements" tile (the current version) open a version directly.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import { activityActionLabel } from "../../api/types";
import type { OrgGroup, OrgUser } from "../../api/types";
import { EntitySwitcher, type EntitySwitcherOption } from "../../components/EntitySwitcher";
import { MetricTile } from "../../components/MetricTile";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordHeader } from "../../components/RecordHeader";
import { Spinner } from "../../components/Spinner";
import { useConfirmedAction } from "../../components/useConfirmedAction";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import { refreshComplianceNavVisibility } from "./useComplianceNavVisibility";
import { StandardApplicabilityPanel } from "./StandardApplicabilityPanel";
import { type EditableStandardFieldValues, StandardFormModal } from "./StandardFormModal";
import { StandardMembersSection } from "./StandardMembersSection";
import { StandardProjectsPanel } from "./StandardProjectsPanel";
import { StandardVersionsSection } from "./StandardVersionsSection";
import type {
  ComplianceActionType,
  ComplianceAuditEvent,
  ComplianceStandard,
  ComplianceStandardVersion,
  ProjectComplianceStatus,
} from "./types";
import { userDisplayName } from "./types";
import { Badge } from "../../components/Badge";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { DetailCard } from "../../components/DetailCard";
import { useStrings } from "../../context/TerminologyContext";
import { MarkdownView } from "../../components/MarkdownView";

type StandardWorkspaceSection = "overview" | "versions" | "members" | "history" | "projects";

/** The version an Overview click-through lands on: the latest published version or, with none published, the latest version
 * overall, so a standard with only a draft still gives the "Requirements" tile a target. */
function currentVersion(versions: ComplianceStandardVersion[]): ComplianceStandardVersion | null {
  if (versions.length === 0) return null;
  const published = versions.filter((v) => v.status === "published");
  const pool = published.length > 0 ? published : versions;
  return pool.reduce((latest, v) => (v.version_number > latest.version_number ? v : latest));
}

/** `EntitySwitcher` loader — reuses `listStandardsAcrossMyOrgs`,
 * the same cross-org fan-out `StandardListPage.tsx` uses, rather than
 * duplicating it here. */
async function loadStandardSwitcherOptions(): Promise<EntitySwitcherOption[]> {
  const { rows } = await complianceApi.listStandardsAcrossMyOrgs();
  return rows.map((s) => ({ id: s.id, label: `${s.reference} — ${s.name}`, href: `/standards/${s.id}` }));
}

export function StandardWorkspacePage() {
  const strings = useStrings();
  const { standardId, section: sectionParam, versionId } = useParams<{ standardId: string; section?: string; versionId?: string }>();
  const { showToast } = useToast();

  const [standard, setStandard] = useState<ComplianceStandard | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [actionTypes, setActionTypes] = useState<ComplianceActionType[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [orgGroups, setOrgGroups] = useState<OrgGroup[]>([]);
  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [history, setHistory] = useState<ComplianceAuditEvent[] | null>(null);
  const [exporting, setExporting] = useState(false);
  const [versions, setVersions] = useState<ComplianceStandardVersion[] | null>(null);
  const [requirementCount, setRequirementCount] = useState<number | null>(null);
  const [projectSummary, setProjectSummary] = useState<ProjectComplianceStatus[] | null>(null);

  const section: StandardWorkspaceSection =
    sectionParam === "versions" || sectionParam === "members" || sectionParam === "history" || sectionParam === "projects"
      ? sectionParam
      : "overview";

  async function reloadStandard() {
    if (!standardId) return;
    try {
      const loaded = await complianceApi.getStandardById(standardId);
      setStandard(loaded);
      setNotFound(false);
    } catch {
      setNotFound(true);
    }
  }

  useResetOnChange([standardId], () => {
    setStandard(null);
    setNotFound(false);
  });
  useLoadOnChange(reloadStandard, [standardId]);

  useEffect(() => {
    if (!standard) return;
    complianceApi.listActionTypes(standard.organization_id).then(setActionTypes);
    api.get<OrgUser[]>(`/api/v1/orgs/${standard.organization_id}/users`).then(setOrgUsers);
    api.get<OrgGroup[]>(`/api/v1/orgs/${standard.organization_id}/groups`).then(setOrgGroups);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standard?.organization_id]);

  // Overview stats: the version count, this standard's slice of §20 status (projects and compliant tiles) and the current version's
  // requirement count, fetched once the version list identifies the current version (`listRequirements` already exists and is
  // cheap, so no new backend field is needed).
  useResetOnChange([standard?.organization_id, standard?.id], () => {
    setVersions(null);
    setRequirementCount(null);
  });

  useEffect(() => {
    if (!standard) return;
    complianceApi.listStandardVersions(standard.organization_id, standard.id).then(setVersions);
    complianceApi.getStandardProjectSummary(standard.organization_id, standard.id).then(setProjectSummary);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standard?.organization_id, standard?.id]);

  const latestVersion = useMemo(() => (versions ? currentVersion(versions) : null), [versions]);

  useEffect(() => {
    if (!standard || !latestVersion) return;
    complianceApi
      .listRequirements(standard.organization_id, standard.id, latestVersion.id)
      .then((requirements) => setRequirementCount(requirements.length));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standard?.organization_id, standard?.id, latestVersion?.id]);

  useResetOnChange([section, standard?.organization_id, standard?.id], () => setHistory(null));

  useEffect(() => {
    if (section !== "history" || !standard) return;
    complianceApi
      .getStandardHistory(standard.organization_id, standard.id)
      .then(setHistory)
      .catch((err) => showToast(toErrorMessage(err, "Could not load history."), "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, standard?.organization_id, standard?.id]);

  async function handleArchiveToggle() {
    if (!standard) return;
    try {
      const updated = standard.is_archived
        ? await complianceApi.unarchiveStandard(standard.organization_id, standard.id)
        : await complianceApi.archiveStandard(standard.organization_id, standard.id);
      showToast(updated.is_archived ? "Standard archived." : "Standard unarchived.");
      setStandard(updated);
      refreshComplianceNavVisibility();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update standard."), "error");
    }
  }

  async function handleExport() {
    if (!standard) return;
    setExporting(true);
    try {
      const blob = await complianceApi.exportStandard(standard.organization_id, standard.id);
      downloadBlob(blob, `${standard.reference}-export.json`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not export standard."), "error");
    } finally {
      setExporting(false);
    }
  }

  const archiveAction = useConfirmedAction(
    standard && {
      label: standard.is_archived ? "Unarchive" : "Archive",
      danger: !standard.is_archived,
      title: standard.is_archived ? `Unarchive "${standard.name}"?` : `Archive "${standard.name}"?`,
      message: standard.is_archived
        ? "This standard will reappear in the default (non-archived) list."
        : "This standard will be hidden from the default list. Nothing referencing it is deleted.",
      onConfirm: handleArchiveToggle,
    },
  );

  if (notFound) {
    return <p className="text-muted">This compliance standard could not be found, or you do not have access to it.</p>;
  }
  if (!standard) return <Spinner />;

  return (
    <div className="stack">
      <RecordHeader
        recordLabel="Standard"
        back={{ to: "/standards", label: "Compliance Standards" }}
        title={`${standard.reference} — ${standard.name}`}
        titleAddon={<EntitySwitcher label="Switch standard" currentId={standard.id} loadOptions={loadStandardSwitcherOptions} />}
        badges={standard.is_archived ? <Badge>Archived</Badge> : undefined}
        onEdit={() => setEditing(true)}
        actions={[
          { label: exporting ? "Exporting…" : "Export", onSelect: () => { if (!exporting) void handleExport(); } },
          archiveAction.item,
        ]}
      />
      {archiveAction.dialog}

      {section === "overview" && (
        <div className="stack">
          <div className="grid grid-metrics">
            <MetricTile label="Versions" value={versions?.length ?? "…"} to={`/standards/${standard.id}/versions`} />
            <MetricTile
              label="Requirements"
              value={requirementCount ?? (latestVersion ? "…" : 0)}
              to={latestVersion ? `/standards/${standard.id}/versions/${latestVersion.id}` : `/standards/${standard.id}/versions`}
            />
            <MetricTile label={strings.filters.projects} value={projectSummary?.length ?? "…"} to={`/standards/${standard.id}/projects`} />
            <MetricTile
              label="Compliant"
              value={projectSummary ? projectSummary.filter((p) => p.overall_compliance_state === "compliant").length : "…"}
              to={`/standards/${standard.id}/projects?state=compliant`}
            />
          </div>
          <DetailCard>
            {standard.description ? <MarkdownView text={standard.description} /> : <p><span className="text-muted">No description.</span></p>}
            {standard.issuing_organisation && <p className="text-muted">Issued by {standard.issuing_organisation}</p>}
            <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
              <span className="text-muted">Owner:</span>
              <PrincipalBadge principal={standard.owner} />
            </div>
          </DetailCard>
          <StandardApplicabilityPanel standard={standard} onStandardChanged={setStandard} />
        </div>
      )}

      {section === "versions" && (
        <StandardVersionsSection orgId={standard.organization_id} standard={standard} actionTypes={actionTypes} initialVersionId={versionId ?? null} />
      )}

      {section === "members" && (
        <StandardMembersSection orgId={standard.organization_id} standard={standard} orgUsers={orgUsers} orgGroups={orgGroups} />
      )}

      {section === "projects" && (
        <StandardProjectsPanel orgId={standard.organization_id} standard={standard} />
      )}

      {section === "history" && (
        history === null ? (
          <Spinner />
        ) : history.length === 0 ? (
          <p className="text-muted">No history yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {history.map((h) => (
              <li key={h.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "var(--space-2) 0" }}>
                <span className="text-muted">{new Date(h.created_at).toLocaleString()}</span>
                {" — "}
                {userDisplayName(orgUsers, h.actor_id)} — {activityActionLabel(h.action)}
              </li>
            ))}
          </ul>
        )
      )}

      {editing && (
        <StandardFormModal
          initial={standard}
          orgId={standard.organization_id}
          orgUsers={orgUsers}
          error={editError}
          onCancel={() => {
            setEditing(false);
            setEditError(null);
          }}
          onSave={async (values) => {
            setEditError(null);
            try {
              const updated = await complianceApi.updateStandard(
                standard.organization_id, standard.id, values as EditableStandardFieldValues,
              );
              showToast("Standard updated.");
              setEditing(false);
              setStandard(updated);
            } catch (err) {
              setEditError(toErrorMessage(err, "Could not update standard."));
            }
          }}
        />
      )}
    </div>
  );
}
