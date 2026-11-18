/**
 * Module: modules/architecture/BaselineRecordDialog
 *
 * One record of a baseline as it stood when the baseline was taken: every field the snapshot holds, with a list field (ports, boxes,
 * states, tags) as one line per entry. Read only; the record on the live model is not touched or linked, since it may have changed or
 * been deleted since.
 */
import { useEffect, useState } from "react";

import { Modal } from "../../components/Modal";
import { RecordField, RecordFieldGroup } from "../../components/RecordDetailParts";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage } from "../../context/ToastContext";
import { projectBaselineApi } from "./api";
import { BASELINE_HEADING_KEYS, baselineFieldLabel, baselineValueText } from "./baselineModel";
import { BASELINE_TYPE_LABEL, type BaselineItem, type BaselineRecord } from "./types";

/** A list entry as one line: text as it is, an object as compact JSON. */
function entryText(entry: unknown): string {
  return typeof entry === "string" ? entry : JSON.stringify(entry);
}

/**
 * @param projectId The project.
 * @param baselineId The baseline the record belongs to.
 * @param record The record to show.
 * @param onClose Called when the dialog is dismissed.
 */
export function BaselineRecordDialog({
  projectId, baselineId, record, onClose,
}: { projectId: string; baselineId: string; record: BaselineRecord; onClose: () => void }) {
  const [item, setItem] = useState<BaselineItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    projectBaselineApi(projectId).item(baselineId, record.id)
      .then((found) => { if (live) setItem(found); })
      .catch((err) => { if (live) setError(toErrorMessage(err, "This record could not be read.")); });
    return () => { live = false; };
  }, [projectId, baselineId, record.id]);

  const kind = BASELINE_TYPE_LABEL[record.item_type]?.replace(/s$/, "") ?? "Record";
  return (
    <Modal title={`${kind} ${record.code} ${record.name}`} onClose={onClose} size="lg">
      {error && <p className="text-muted">{error}</p>}
      {!error && !item && <Spinner />}
      {item && (
        <div className="stack">
          {Object.entries(item.content)
            .filter(([key]) => !BASELINE_HEADING_KEYS.includes(key))
            .map(([key, value]) => (Array.isArray(value) && value.length > 0
              ? (
                <RecordFieldGroup key={key} helpNotNeeded label={baselineFieldLabel(key)}>
                  <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{value.map((entry, n) => <li key={n}>{entryText(entry)}</li>)}</ul>
                </RecordFieldGroup>
              )
              : <RecordField key={key} label={baselineFieldLabel(key)} value={baselineValueText(value)} />
            ))}
        </div>
      )}
    </Modal>
  );
}
