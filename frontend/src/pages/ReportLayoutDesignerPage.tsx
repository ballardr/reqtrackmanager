/**
 * Module: pages/ReportLayoutDesignerPage
 *
 * The designer of one report layout, at `/projects/:projectId/report-layouts/:layoutId` and
 * `/orgs/:orgId/report-layouts/:layoutId`. It only binds the URL to a scope (`reportLayoutApi`), supplies where
 * Back leads (Report setup of Project Admin, Templates & reports of Org Admin) and, for an organisation layout,
 * the projects a preview can be narrowed to; the designer itself is `ReportLayoutDesigner`.
 */
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import { reportLayoutApi, type LayoutScope } from "../api/reportLayouts";
import type { ProjectListItem } from "../api/types";
import { ReportLayoutDesigner } from "../components/ReportLayoutDesigner";
import { Spinner } from "../components/Spinner";
import { useLoadOnChange } from "../hooks/useLoadOnChange";

export function ReportLayoutDesignerPage() {
  const { projectId, orgId, layoutId } = useParams<{ projectId?: string; orgId?: string; layoutId: string }>();
  const kind: LayoutScope["kind"] | null = projectId ? "project" : orgId ? "organization" : null;
  const scopeId = projectId ?? orgId ?? null;
  const layouts = useMemo(() => (kind && scopeId ? reportLayoutApi({ kind, id: scopeId }) : null), [kind, scopeId]);
  const [projects, setProjects] = useState<{ value: string; label: string }[] | undefined>(undefined);

  useLoadOnChange(async () => {
    if (kind !== "organization" || !scopeId) return;
    try {
      const list = await api.get<ProjectListItem[]>(`/api/v1/projects?archived=false&organization_id=${scopeId}`);
      setProjects(list.map((p) => ({ value: p.id, label: p.name })));
    } catch {
      setProjects(undefined);
    }
  }, [kind, scopeId]);

  if (!kind || !scopeId || !layouts || !layoutId) return <Spinner />;
  const backTo = kind === "project" ? `/projects/${scopeId}/admin/reportSetup` : `/orgs/${scopeId}/admin/templates-reports`;
  return <ReportLayoutDesigner api={layouts} layoutId={layoutId} backTo={backTo} projectOptions={projects} />;
}
