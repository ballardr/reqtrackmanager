/**
 * Module: pages/ReportPackPage
 *
 * The editor of one report pack, at `/projects/:projectId/report-packs/:packId` and
 * `/orgs/:orgId/report-packs/:packId`. It only binds the URL to a scope (`reportPackApi`) and supplies where Back
 * leads (Report setup of Project Admin, Templates & reports of Org Admin); the editor itself is `ReportPackEditor`.
 */
import { useMemo } from "react";
import { useParams } from "react-router-dom";

import type { LayoutScope } from "../api/reportLayouts";
import { reportPackApi } from "../api/reportPacks";
import { ReportPackEditor } from "../components/ReportPackEditor";
import { Spinner } from "../components/Spinner";

export function ReportPackPage() {
  const { projectId, orgId, packId } = useParams<{ projectId?: string; orgId?: string; packId: string }>();
  const kind: LayoutScope["kind"] | null = projectId ? "project" : orgId ? "organization" : null;
  const scopeId = projectId ?? orgId ?? null;
  const packs = useMemo(() => (kind && scopeId ? reportPackApi({ kind, id: scopeId }) : null), [kind, scopeId]);
  if (!kind || !scopeId || !packs || !packId) return <Spinner />;
  const backTo = kind === "project" ? `/projects/${scopeId}/admin/reportSetup` : `/orgs/${scopeId}/admin/templates-reports`;
  return <ReportPackEditor api={packs} packId={packId} backTo={backTo} />;
}
