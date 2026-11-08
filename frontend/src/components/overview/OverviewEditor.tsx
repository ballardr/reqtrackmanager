/**
 * Module: components/overview/OverviewEditor
 *
 * Edits an overview layout on the page itself: the widgets are the grid the viewers see, with a handle, a corner and
 * buttons on each, and a sticky bar above it holds what is not a single widget's (add a widget, the overview's project
 * scope, restore the default, cancel, save). One component serves a project's overview and, with labelled blocks in
 * place of data, the organisation's default, so the two cannot drift.
 *
 * Responsibilities:
 * - Load the layout in force and the server's catalogue, keep a draft, and save the whole layout in one request.
 * - Show the draft with live figures (a project), so the effect of a change is seen as it is made.
 * - Open a widget's settings in a side panel; the draft changes as the settings do, and "Done" closes the panel.
 * - Restore the default (remove the project's or organisation's own layout) after a confirmation, offered only once
 *   the layout is the project's own, and ask before discarding changes.
 *
 * Design decisions:
 * - Save and Cancel are always on screen (the bar is sticky), the same reason a form's actions sit in its header.
 * - A widget the person hides stays in the grid, dimmed, so it can be shown again; it requests no data.
 */
import { useCallback, useMemo, useState } from "react";

import { api } from "../../api/client";
import { availableScopes, projectScopeApi, PROJECT_SCOPES } from "../../api/projectScope";
import type { OverviewCatalogue, OverviewLayout, OverviewLayoutBody, OverviewScope, OverviewWidget } from "../../api/types";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useMutation } from "../../hooks/useMutation";
import { useOverviewMetrics } from "../../hooks/useOverviewMetrics";
import { cleanedForSave, defaultWidget } from "../../utils/overviewWidgets";
import { ConfirmDialog } from "../ConfirmDialog";
import { FieldHelp } from "../FieldHelp";
import { FormActions } from "../FormActions";
import { SidePanel } from "../SidePanel";
import { Spinner } from "../Spinner";
import { titleOf } from "./overviewTitles";
import { OverviewWidgetGrid } from "./OverviewWidgetGrid";
import { OverviewWidgetSettings } from "./OverviewWidgetSettings";
import { InlineSelect } from "../LabeledSelect";

/** Where the editor reads and writes: one project's own layout, or the organisation's default. */
export type OverviewEditTarget = { kind: "project"; projectId: string } | { kind: "organisation"; organizationId: string };

function basePath(target: OverviewEditTarget): string {
  return target.kind === "project" ? `/api/v1/projects/${target.projectId}` : `/api/v1/orgs/${target.organizationId}`;
}

/**
 * @param target The tier to edit.
 * @param onSaved Called after a save or a restore (the page reloads its layout and leaves edit mode).
 * @param onCancel Called when the person leaves without saving.
 */
export function OverviewEditor({
  target, onSaved, onCancel,
}: { target: OverviewEditTarget; onSaved: () => void; onCancel: () => void }) {
  const strings = useStrings();
  const t = strings.overviewWidgets;
  const run = useMutation();
  const { showToast } = useToast();
  const path = basePath(target);
  const projectId = target.kind === "project" ? target.projectId : undefined;
  const [layout, setLayout] = useState<OverviewLayout | null>(null);
  const [catalogue, setCatalogue] = useState<OverviewCatalogue | null>(null);
  const [scopes, setScopes] = useState<OverviewScope[]>(["this"]);
  const [draft, setDraft] = useState<OverviewLayoutBody | null>(null);
  const [settingsId, setSettingsId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"restore" | "discard" | null>(null);
  const metrics = useOverviewMetrics(projectId, draft?.widgets ?? null, draft?.scope ?? "this", t.figureError);

  const reload = useCallback(async () => {
    try {
      const [loadedLayout, loadedCatalogue, options] = await Promise.all([
        api.get<OverviewLayout>(`${path}/overview-layout`),
        api.get<OverviewCatalogue>(`${path}/overview-catalogue`),
        projectId ? projectScopeApi.options(projectId).catch(() => null) : Promise.resolve(null),
      ]);
      setLayout(loadedLayout);
      setCatalogue(loadedCatalogue);
      setScopes(projectId ? availableScopes(options) : PROJECT_SCOPES);
      setDraft({ scope: loadedLayout.scope, widgets: loadedLayout.widgets });
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, t.loadFailed));
    }
  }, [path, projectId, t.loadFailed]);
  useLoadOnChange(reload, [path]);

  const dirty = useMemo(
    () => layout !== null && draft !== null && JSON.stringify(draft) !== JSON.stringify({ scope: layout.scope, widgets: layout.widgets }),
    [layout, draft],
  );

  if (loadError) return <p style={{ color: "var(--color-danger)" }}>{loadError}</p>;
  if (!layout || !catalogue || !draft) return <Spinner />;

  const update = (widgets: OverviewWidget[]) => setDraft({ ...draft, widgets });
  const settingsWidget = draft.widgets.find((w) => w.id === settingsId) ?? null;
  const atCap = draft.widgets.length >= catalogue.max_widgets;
  const typeLabels = Object.fromEntries(catalogue.widget_types.map((w) => [w.key, t.typeLabel[w.key] ?? w.label]));
  const nameOf = (widget: OverviewWidget) => titleOf(widget, metrics.results?.[widget.id], strings) || typeLabels[widget.type] || widget.type;

  const save = async () => {
    setSaveError(null);
    try {
      await api.put(`${path}/overview-layout`, { scope: draft.scope, widgets: cleanedForSave(draft.widgets) });
    } catch (err) {
      setSaveError(toErrorMessage(err, t.saveFailed));
      return;
    }
    showToast(t.saved);
    onSaved();
  };

  const restore = async () => {
    setConfirm(null);
    if (await run(() => api.delete(`${path}/overview-layout`), { success: t.restored, failure: t.restoreFailed })) onSaved();
  };

  const add = (type: string) => {
    if (!type) return;
    const widget = defaultWidget(type, catalogue, draft.widgets.map((w) => w.id));
    update([...draft.widgets, widget]);
    setSettingsId(widget.id);
  };

  return (
    <div className="stack" data-overview-editor={target.kind}>
      <div className="overview-edit-bar">
        <FormActions
          error={saveError} saveLabel={t.save} onSave={() => void save()} onCancel={() => (dirty ? setConfirm("discard") : onCancel())}
          leading={(
            <span className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
              <InlineSelect
                autoWidth ariaLabel={t.addWidget} value="" placeholder={t.addWidget} disabled={atCap}
                onChange={add}
                options={catalogue.widget_types.map((w) => ({ value: w.key, label: t.typeLabel[w.key] ?? w.label }))}
              />
              {(scopes.length > 1 || draft.scope !== "this") && (
                <>
                  <InlineSelect<OverviewScope>
                    autoWidth ariaLabel={strings.projectScope.label} value={draft.scope} placeholder={null}
                    onChange={(scope) => setDraft({ ...draft, scope })}
                    options={PROJECT_SCOPES.filter((scope) => scopes.includes(scope) || scope === draft.scope).map((scope) => ({
                      value: scope,
                      label: strings.projectScope.options[scope],
                    }))}
                  />
                  <FieldHelp label={strings.projectScope.label} help={strings.help.overviewScope} />
                </>
              )}
              <span className="text-muted">{t.count(draft.widgets.length, catalogue.max_widgets)}</span>
            </span>
          )}
        >
          {layout.source === "own" && <button type="button" className="btn" onClick={() => setConfirm("restore")}>{t.restore}</button>}
        </FormActions>
      </div>
      {draft.widgets.length === 0 && <p className="text-muted">{t.empty}</p>}
      <OverviewWidgetGrid
        widgets={draft.widgets} scope={draft.scope} metrics={metrics} projectId={projectId} placeholders={target.kind === "organisation"} typeLabels={typeLabels}
        edit={{ onChange: update, onOpenSettings: setSettingsId }}
      />
      {settingsWidget && (
        <SidePanel title={t.settingsTitle(nameOf(settingsWidget))} onClose={() => setSettingsId(null)} dirty={false}>
          <FormActions onCancel={() => setSettingsId(null)} onSave={() => setSettingsId(null)} saveLabel={t.done} />
          <OverviewWidgetSettings
            widget={settingsWidget} catalogue={catalogue} projectId={projectId} scopes={scopes}
            onChange={(next) => update(draft.widgets.map((w) => (w.id === next.id ? next : w)))}
          />
        </SidePanel>
      )}
      {confirm === "restore" && (
        <ConfirmDialog
          title={t.restoreTitle} message={target.kind === "project" ? t.restoreBody : t.restoreOrgBody} confirmLabel={t.restore}
          onConfirm={() => void restore()} onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === "discard" && (
        <ConfirmDialog
          title={t.discardTitle} message={t.discardBody} confirmLabel={t.discard}
          onConfirm={() => { setConfirm(null); onCancel(); }} onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
