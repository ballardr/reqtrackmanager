/**
 * Module: components/overview/OrgOverviewDefaultPanel
 *
 * Organisation administration's "Default overview": the layout every project of the organisation shows unless it
 * (or a parent project) has its own. The section body is a compact row (built-in or customised, and the widget
 * count) with a button that opens the shared overview editor in a large dialog, so the page stays a short list of
 * settings. The editor is the one the project overview uses, with a labelled block for each widget in place of data
 * (an organisation default has no project to read figures from).
 *
 * Design decisions:
 * - The dialog's unsaved-changes guard is fed by the editor (`onDirtyChange`), because the editor's state is a drawn
 *   grid the dialog cannot measure from its inputs.
 * - The summary is read again after every close, so it reflects a save or a restore.
 */
import { useCallback, useState } from "react";

import { api } from "../../api/client";
import type { OverviewLayout } from "../../api/types";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useStrings } from "../../context/TerminologyContext";
import { Modal } from "../Modal";
import { OverviewEditor } from "./OverviewEditor";

/**
 * @param organizationId The organisation whose default is edited.
 */
export function OrgOverviewDefaultPanel({ organizationId }: { organizationId: string }) {
  const t = useStrings().overviewWidgets;
  const [summary, setSummary] = useState<{ custom: boolean; widgets: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    try {
      const layout = await api.get<OverviewLayout>(`/api/v1/orgs/${organizationId}/overview-layout`);
      setSummary({ custom: layout.source === "own", widgets: layout.widgets.length });
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [organizationId]);
  useLoadOnChange(load, [organizationId]);

  const close = () => {
    setOpen(false);
    setDirty(false);
    void load();
  };

  return (
    <>
      <div className="row" style={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
        <span className={failed ? undefined : "text-muted"} style={failed ? { color: "var(--color-danger)" } : undefined}>
          {failed ? t.orgSummaryFailed : summary ? (summary.custom ? t.orgCustom(summary.widgets) : t.orgBuiltIn) : ""}
        </span>
        <button type="button" className="btn" onClick={() => setOpen(true)}>{t.orgEdit}</button>
      </div>
      {open && (
        <Modal title={t.orgEditTitle} size="lg" dirty={dirty} onClose={close}>
          <OverviewEditor target={{ kind: "organisation", organizationId }} onSaved={close} onCancel={close} onDirtyChange={setDirty} />
        </Modal>
      )}
    </>
  );
}
