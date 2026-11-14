/**
 * Module: modules/architecture/BaselineDetailPage
 *
 * One baseline as a routed page (`/projects/:projectId/modules/architecture/baselines/:baselineId`): when it was taken and by whom,
 * the architecture records it holds by type (a row opens the record as it stood) and a comparison of it with the live model or
 * another baseline, chosen in "Compare with" (the choice is the `against` query parameter, so a comparison can be linked).
 * The baseline is read only: it is a record of what was, so it has no edit or delete.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { LabeledSelect } from "../../components/LabeledSelect";
import { RecordHeader } from "../../components/RecordHeader";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage } from "../../context/ToastContext";
import { useUrlText } from "../../hooks/useUrlFilter";
import { projectBaselineApi } from "./api";
import { architectureTabPath } from "./architectureTabs";
import { BaselineComparisonView } from "./BaselineComparisonView";
import { BaselineRecordDialog } from "./BaselineRecordDialog";
import { BaselineRecordsCard } from "./BaselineRecordsCard";
import { ARCHITECTURE_HELP } from "./help";
import {
  BASELINE_KIND_LABEL, BASELINE_TYPE_LABEL, type BaselineComparison, type BaselineRecord, type BaselineView, type ProjectBaseline,
} from "./types";

const LIVE = "live";

export function BaselineDetailPage() {
  const { projectId = "", baselineId = "" } = useParams<{ projectId: string; baselineId: string }>();
  const [view, setView] = useState<BaselineView | null>(null);
  const [others, setOthers] = useState<ProjectBaseline[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [against, setAgainst] = useUrlText("against");
  const [comparison, setComparison] = useState<BaselineComparison | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [open, setOpen] = useState<BaselineRecord | null>(null);

  useEffect(() => {
    if (!projectId || !baselineId) return;
    let live = true;
    const api = projectBaselineApi(projectId);
    api.view(baselineId)
      .then((found) => { if (live) { setView(found); setLoadError(null); } })
      .catch((err) => { if (live) setLoadError(toErrorMessage(err, "This baseline could not be found, or you do not have access to it.")); });
    api.list().then((list) => { if (live) setOthers(list.filter((b) => b.id !== baselineId)); }).catch(() => { if (live) setOthers([]); });
    return () => { live = false; };
  }, [projectId, baselineId]);

  useEffect(() => {
    if (!projectId || !baselineId || !against) return;
    let live = true;
    projectBaselineApi(projectId).compare(baselineId, against)
      .then((found) => { if (live) { setComparison(found); setComparisonError(null); } })
      .catch((err) => { if (live) { setComparison(null); setComparisonError(toErrorMessage(err, "The comparison could not be made.")); } });
    return () => { live = false; };
  }, [projectId, baselineId, against]);

  const byType = useMemo(() => {
    const groups = new Map<string, BaselineRecord[]>();
    for (const type of Object.keys(BASELINE_TYPE_LABEL)) groups.set(type, []);
    for (const record of view?.records ?? []) groups.get(record.item_type)?.push(record);
    return [...groups.entries()];
  }, [view]);

  if (!projectId || !baselineId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (view === null) return <Spinner />;

  // A comparison still loading for another choice is not shown against this one.
  const shown = comparison && (comparison.against === "live" ? LIVE : comparison.against_id) === against ? comparison : null;
  const choices = [{ value: LIVE, label: "Live model" }, ...others.map((b) => ({ value: b.id, label: b.label }))];
  return (
    <DetailLayout>
      <RecordHeader
        recordLabel="Baseline"
        title={view.label}
        back={{ to: architectureTabPath(projectId, "baselines"), label: "Baselines" }}
        badges={<Badge tone={view.kind === "stage" ? "info" : "muted"}>{BASELINE_KIND_LABEL[view.kind]}</Badge>}
        subtitle={<>
          Taken {new Date(view.created_at).toLocaleString()}{view.created_by_name ? ` by ${view.created_by_name}` : ""}
          {view.stage_name ? ` · Stage ${view.stage_name}` : ""}
        </>}
      />
      <div className="stack">
        {byType.map(([type, records]) => <BaselineRecordsCard key={type} itemType={type} records={records} onOpen={setOpen} />)}
        <DetailCard heading="Comparison">
          <LabeledSelect
            label="Compare with" help={ARCHITECTURE_HELP.baselineCompareWith} value={against} onChange={setAgainst}
            options={choices} placeholder="Choose what to compare with…" autoWidth
          />
          {comparisonError && <p style={{ color: "var(--color-danger)", margin: 0 }}>{comparisonError}</p>}
          {against && !shown && !comparisonError && <Spinner />}
          {against && shown && <BaselineComparisonView comparison={shown} />}
        </DetailCard>
      </div>
      {open && <BaselineRecordDialog projectId={projectId} baselineId={baselineId} record={open} onClose={() => setOpen(null)} />}
    </DetailLayout>
  );
}
