/**
 * Module: modules/architecture/BaselineComparisonView
 *
 * The result of comparing a baseline with the live model or with another baseline: per record type, the records Added (only in the
 * other side), Removed (only in the baseline viewed) and Changed (field by field, with the entries a list field gained or lost),
 * and how many are unchanged. A record's code is shown as the project writes it; nothing here links to the live record, since a
 * Removed one may be gone.
 */
import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { RecordCode } from "../../components/RecordCode";
import { baselineFieldLabel } from "./baselineModel";
import {
  ARCHITECTURE_STATUS_LABEL, BASELINE_TYPE_LABEL, type BaselineComparison, type BaselineFieldChange, type BaselineRecordRef,
} from "./types";

/** One record reference: its code, name and status. */
function RecordLine({ record }: { record: BaselineRecordRef }) {
  return (
    <span>
      <RecordCode code={record.code} /> {record.name}
      {record.status && <> <span className="text-muted">({ARCHITECTURE_STATUS_LABEL[record.status]})</span></>}
    </span>
  );
}

/** A list of records under a caption, or nothing for an empty list. */
function RecordList({ caption, tone, records }: { caption: string; tone: "accent" | "danger"; records: BaselineRecordRef[] }) {
  if (records.length === 0) return null;
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <div><Badge tone={tone}>{caption}</Badge> <span className="text-muted">{records.length}</span></div>
      <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
        {records.map((r) => <li key={r.code}><RecordLine record={r} /></li>)}
      </ul>
    </div>
  );
}

/** One changed field: before and after for a scalar, the entries gained and lost for a list. */
function FieldLine({ change }: { change: BaselineFieldChange }) {
  const isList = change.added.length > 0 || change.removed.length > 0;
  return (
    <li>
      <strong>{baselineFieldLabel(change.field)}</strong>
      {isList ? (
        <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
          {change.removed.map((entry, n) => <li key={`r${n}`}><Badge tone="danger">Removed</Badge> <code>{entry}</code></li>)}
          {change.added.map((entry, n) => <li key={`a${n}`}><Badge tone="accent">Added</Badge> <code>{entry}</code></li>)}
        </ul>
      ) : (
        <>: <span className="text-muted">{change.before ?? "—"}</span> → {change.after ?? "—"}</>
      )}
    </li>
  );
}

/** @param comparison What the server returned. */
export function BaselineComparisonView({ comparison }: { comparison: BaselineComparison }) {
  return (
    <div className="stack" aria-label="Comparison result">
      <p className="text-muted" style={{ margin: 0 }}>
        {comparison.baseline_label} compared with {comparison.against_label}.
      </p>
      {comparison.types.map((type) => {
        const label = BASELINE_TYPE_LABEL[type.item_type] ?? type.item_type;
        const differs = type.added.length + type.removed.length + type.changed.length;
        return (
          <DetailCard key={type.item_type} heading={label}>
            {differs === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>No differences ({type.unchanged} unchanged).</p>
            ) : (
              <div className="stack">
                <RecordList caption="Added" tone="accent" records={type.added} />
                <RecordList caption="Removed" tone="danger" records={type.removed} />
                {type.changed.length > 0 && (
                  <div className="stack" style={{ gap: "0.25rem" }}>
                    <div><Badge tone="info">Changed</Badge> <span className="text-muted">{type.changed.length}</span></div>
                    <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                      {type.changed.map((record) => (
                        <li key={record.code}>
                          <RecordLine record={record} />
                          <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                            {record.fields.map((field) => <FieldLine key={field.field} change={field} />)}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="text-muted" style={{ margin: 0 }}>{type.unchanged} unchanged.</p>
              </div>
            )}
          </DetailCard>
        );
      })}
    </div>
  );
}
