/**
 * Module: components/ReportCopyDialog
 *
 * The dialog that copies the reports ticked in a project's Report setup list into another project of the organisation:
 * choose the target project and how to settle a name it already uses, preview what would happen, then copy.
 *
 * Responsibilities:
 * - Load the projects the person can copy into (`ReportCopyApi.targets`) and offer them in a select.
 * - Preview first (a dry run) and list each item with its outcome (copy, copy under a new name, skip, already there) and
 *   its warnings, then copy for real; changing the target or the name rule discards a preview, so what is applied is
 *   always what was shown.
 * - After the copy, say what was created or left as it was and link to the target project's report setup.
 *
 * Design decisions: the server decides everything (names, conflicts, warnings), the dialog only shows it, so the preview
 * and the copy cannot disagree. Nothing can be replaced, so there is no replace option. Follows the form header
 * pattern (`FormActions` in the dialog header) and the field help and required-field patterns.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  COPY_ACTION_LABEL, COPY_CONFLICT_LABEL, COPY_KIND_LABEL, type CopyConflict, type CopyItemResult, type CopyItems, type CopyResult,
  type CopyTarget, type ReportCopyApi,
} from "../api/reportCopy";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { copyCount } from "../utils/reportCopySelection";
import { Badge } from "./Badge";
import { CheckboxField } from "./FormFields";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/** The target project's report setup page (where the copies are listed). */
const setupPath = (projectId: string) => `/projects/${projectId}/admin/reportSetup`;

/**
 * @param api The calls, injected so a story runs without a server.
 * @param sourceProjectId The project being copied from.
 * @param items What to copy.
 * @param onClose Called by Cancel and Close.
 * @param onCopied Called once a copy has been applied, so the list behind can reload.
 */
export function ReportCopyDialog({
  api, sourceProjectId, items, onClose, onCopied,
}: { api: ReportCopyApi; sourceProjectId: string; items: CopyItems; onClose: () => void; onCopied?: () => void }) {
  const strings = useStrings();
  const text = strings.reportCopy;
  const { showToast } = useToast();
  const { refreshUser } = useAuth();
  const [targets, setTargets] = useState<CopyTarget[] | null>(null);
  const [targetsFailed, setTargetsFailed] = useState(false);
  const [targetId, setTargetId] = useState("");
  const [conflict, setConflict] = useState<CopyConflict>("rename");
  const [favourites, setFavourites] = useState(true);
  const [plan, setPlan] = useState<CopyResult | null>(null);
  const [result, setResult] = useState<CopyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = copyCount(items);

  useEffect(() => {
    let cancelled = false;
    api.targets(sourceProjectId).then(
      (found) => { if (!cancelled) setTargets(found); },
      () => { if (!cancelled) setTargetsFailed(true); },
    );
    return () => { cancelled = true; };
  }, [api, sourceProjectId]);

  const targetName = useMemo(() => targets?.find((t) => t.id === targetId)?.name ?? "", [targets, targetId]);
  const request = (dryRun: boolean) => ({ ...items, source_project_id: sourceProjectId, on_conflict: conflict, favourites, dry_run: dryRun });
  const doing = plan?.items.filter((i) => i.action === "create" || i.action === "rename").length ?? 0;

  /** Changing what was previewed throws the preview away, so a copy always matches what was shown. */
  const change = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setPlan(null);
    setError(null);
  };

  async function run(dryRun: boolean) {
    setBusy(true);
    setError(null);
    try {
      const done = await api.copy(targetId, request(dryRun));
      if (dryRun) {
        setPlan(done);
        return;
      }
      setResult(done);
      showToast(text.toast(targetName));
      await refreshUser().catch(() => {});
      onCopied?.();
    } catch (err) {
      setError(toErrorMessage(err, text.failed));
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    const created = result.items.filter((i) => i.action === "create" || i.action === "rename").length;
    const left = result.items.length - created;
    return (
      <Modal title={text.title(total)} onClose={onClose}>
        <div className="stack">
          <FormActions onCancel={onClose} cancelLabel={text.close} />
          <p role="status" style={{ margin: 0 }}>
            {text.done(created, targetName)}{left > 0 && ` ${text.doneSkipped(left)}`}
            {result.favourites_carried > 0 && ` ${text.favouritesCarried(result.favourites_carried)}`}
          </p>
          <ItemList items={result.items} />
          <Link to={setupPath(result.target_project_id)}>{text.open(targetName)}</Link>
        </div>
      </Modal>
    );
  }

  const noTargets = targets !== null && targets.length === 0;
  return (
    <Modal title={text.title(total)} onClose={onClose} size="lg">
      <div className="stack">
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void run(plan === null)}
          saveLabel={plan === null ? (busy ? text.previewing : text.previewButton) : text.copyButton(doing)}
          saveDisabled={busy || targetId === "" || (plan !== null && doing === 0)}
          cancelDisabled={busy}
        />
        <p className="text-muted" style={{ margin: 0 }}>{text.note}</p>
        {targetsFailed && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{text.targetsFailed}</p>}
        {noTargets && <p className="text-muted" style={{ margin: 0 }}>{text.noTargets}</p>}
        <LabeledSelect
          required label={text.targetLabel} help={strings.help.reportCopyTarget} value={targetId}
          onChange={change(setTargetId)} placeholder={text.targetPlaceholder} disabled={targets === null || noTargets}
          options={(targets ?? []).map((t) => ({ value: t.id, label: t.name }))}
        />
        <LabeledSelect
          label={text.conflictLabel} help={strings.help.reportCopyConflict} value={conflict} placeholder={null}
          onChange={change((value: string) => setConflict(value as CopyConflict))}
          options={(Object.keys(COPY_CONFLICT_LABEL) as CopyConflict[]).map((key) => ({ value: key, label: COPY_CONFLICT_LABEL[key] }))}
        />
        <CheckboxField
          label={text.favouritesLabel} hint={text.favouritesHint} helpNotNeeded checked={favourites} onChange={change(setFavourites)}
        />
        {plan && (
          <>
            {plan.items.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.nothingToDo}</p>}
            <ItemList items={plan.items} />
            {plan.warnings.map((warning) => <p key={warning} className="text-muted" style={{ margin: 0 }}>{warning}</p>)}
          </>
        )}
      </div>
    </Modal>
  );
}

/** The items of a plan or result, one per line, with the outcome and any warnings. */
function ItemList({ items }: { items: CopyItemResult[] }) {
  const text = useStrings().reportCopy;
  return (
    <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-2)" }} aria-label={text.headingItem}>
      {items.map((item) => (
        <li key={`${item.kind}:${item.source_id}`} className="stack" style={{ gap: 0 }}>
          <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
            <Badge>{COPY_KIND_LABEL[item.kind]}</Badge>
            <strong>{item.action === "rename" ? text.arrow(item.name, item.new_name) : item.name}</strong>
            <span className="text-muted">{COPY_ACTION_LABEL[item.action]}</span>
          </span>
          {item.origin !== "project" && item.kind !== "placement" && (
            <span className="text-muted" style={{ fontSize: "0.85rem" }}>{text.shared}</span>
          )}
          {item.warnings.map((warning) => (
            <span key={warning} className="text-muted" style={{ fontSize: "0.85rem" }}>{warning}</span>
          ))}
        </li>
      ))}
    </ul>
  );
}
