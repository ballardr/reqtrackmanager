/**
 * Module: components/overview/OrgDashboardView
 *
 * One dashboard page of an organisation, drawn through the same grid the project overview uses, with its
 * figures read in one batched request. An organisation administrator gets a "Customise" action (in the page's title
 * row, through `PageActions`) that turns the page into the shared overview editor.
 *
 * Responsibilities:
 * - Load the page and its layout, and answer 404 as "not found" (a page the person may not see reads the same).
 * - Show the grid, a notice while figures are scoped to what the person can open, and the editor on request.
 *
 * Design decisions: the page reads the figures the person may see, so the same dashboard shows different counts to
 * different members; the server decides what a figure counts, never this view.
 */
import { SlidersHorizontal } from "lucide-react";
import { useCallback, useState } from "react";

import { ApiError, api } from "../../api/client";
import type { OrgDashboardLayout } from "../../api/types";
import { useStrings } from "../../context/TerminologyContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useOverviewMetrics } from "../../hooks/useOverviewMetrics";
import { PageActions } from "../PageActions";
import { Spinner } from "../Spinner";
import { OverviewEditor } from "./OverviewEditor";
import { OverviewWidgetGrid } from "./OverviewWidgetGrid";

/**
 * @param orgId The organisation.
 * @param dashboardId The page (`overview` for the built-in first page).
 * @param scopedFigures True while the person's figures are limited to what they can open, so the page says so.
 */
export function OrgDashboardView({ orgId, dashboardId, scopedFigures = false }: { orgId: string; dashboardId: string; scopedFigures?: boolean }) {
  const strings = useStrings();
  const t = strings.orgDashboards;
  const [layout, setLayout] = useState<OrgDashboardLayout | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const path = `/api/v1/orgs/${orgId}/dashboards/${dashboardId}`;
  const metrics = useOverviewMetrics(`${path}/metrics`, layout?.widgets ?? null, "this", strings.common.error);

  const load = useCallback(async () => {
    try {
      setLayout(await api.get<OrgDashboardLayout>(path));
      setError(null);
    } catch (err) {
      setLayout(null);
      setError(err instanceof ApiError && err.status === 404 ? t.notFound : err instanceof ApiError ? err.message : strings.common.error);
    }
  }, [path, t.notFound, strings.common.error]);
  useLoadOnChange(load, [path]);

  if (error) return <p className="text-muted">{error}</p>;
  if (!layout || (!editing && !metrics.results)) return <Spinner />;

  if (editing) {
    return (
      <OverviewEditor
        target={{ kind: "dashboard", organizationId: orgId, dashboardId }} onCancel={() => setEditing(false)}
        onSaved={() => { setEditing(false); void load(); }}
      />
    );
  }
  return (
    <div className="stack">
      {layout.dashboard.can_manage && (
        <PageActions>
          <button type="button" className="btn" onClick={() => setEditing(true)}>
            <SlidersHorizontal /> {t.customise}
          </button>
        </PageActions>
      )}
      {metrics.error && <p style={{ color: "var(--color-danger)" }}>{metrics.error}</p>}
      {layout.widgets.length === 0 && <p className="text-muted">{t.emptyPage}</p>}
      <OverviewWidgetGrid widgets={layout.widgets} scope="this" metrics={metrics} organizationId={orgId} />
      {scopedFigures && <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>{t.scopedNotice}</p>}
    </div>
  );
}
