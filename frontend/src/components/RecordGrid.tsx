/**
 * Module: components/RecordGrid
 *
 * The bulk edit grid of a record list (docs/ux-style-guide.md, "Pattern: bulk edit grid"): the list's own rows and
 * filters, with the type's editable columns as cells, so many records can be adjusted without opening each one.
 *
 * - **Data** comes from `GET .../records/{type}/grid` with the page's filters, so the grid shows exactly what the
 *   list and its export show. A cell is a shared control for its kind: a select for a closed value, a date, a number
 *   or a checkbox. Free text is not edited here (it is edited in the record's form, where it can grow).
 * - **Save** sends one request per changed row (`PATCH .../rows/{code}`) with the cells that changed and what they
 *   held when loaded, so one failing row never blocks the others and a cell someone else changed meanwhile is
 *   refused, not overwritten. A saved row is replaced by the server's answer; a failed row stays changed, with its
 *   message under it. The outcome is one toast: "N saved, M failed".
 * - **Read-only** rows and cells (a record at a terminal outcome, another project's record, a score cell on a Pain
 *   Point scored per persona) are shown as text with the reason in a tooltip, reachable by keyboard.
 * - **Keyboard**: Tab moves between cells; Enter (Shift+Enter) moves to the same column in the next (previous) row, and so do
 *   the up and down arrows in a date or number cell; the arrows in a select change its value as usual.
 *
 * It knows no record type or module: columns, choices, locks and rules all come from the server. Unsaved changes
 * are kept when the page's filters change and a row stays in the list, and the browser asks before the page is closed.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { recordTablesApi, type GridColumn, type GridRow, type RecordGridData, type RecordTablesApi } from "../api/recordTables";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { ConfirmDialog } from "./ConfirmDialog";
import { InlineCheckbox, InlineTextInput } from "./FormFields";
import { InlineSelect } from "./LabeledSelect";
import { Spinner } from "./Spinner";
import { Tooltip } from "./Tooltip";

/** Rows saved at once; each is its own request, this only bounds how many are in flight. */
const SAVE_CONCURRENCY = 5;

type Edits = Record<string, Record<string, string>>;

/** `values` without `key`. */
function without<T>(values: Record<string, T>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(values).filter(([k]) => k !== key));
}

/**
 * @param projectId The project whose list this is.
 * @param recordType The registered record type.
 * @param filters The page's filters as a query string without `?` (the same the Export menu sends).
 * @param contextKeys Keys of read-only columns shown beside the code for orientation; defaults to the first text column.
 * @param recordHref Where a row's code links to (the record's page); omit for plain text.
 * @param onSaved Called after at least one row saved, so the page can refresh anything else it shows.
 * @param tables Injectable calls (stories pass fakes).
 */
export function RecordGrid({
  projectId, recordType, filters = "", contextKeys, recordHref, onSaved, tables = recordTablesApi,
}: {
  projectId: string;
  recordType: string;
  filters?: string;
  contextKeys?: string[];
  recordHref?: (row: GridRow) => string;
  onSaved?: () => void;
  tables?: RecordTablesApi;
}) {
  const { showToast } = useToast();
  const [data, setData] = useState<RecordGridData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Edits>({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [confirmReload, setConfirmReload] = useState(false);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let active = true;
    tables.grid(projectId, recordType, filters)
      .then((next) => {
        if (!active) return;
        setData(next);
        setLoadError(null);
        // Keep the changes of rows that are still listed; a row that left the list takes its changes with it.
        const present = new Set(next.rows.map((r) => r.id));
        setEdits((current) => Object.fromEntries(Object.entries(current).filter(([id]) => present.has(id))));
      })
      .catch((err) => active && setLoadError(toErrorMessage(err, "Could not load the grid.")));
    return () => {
      active = false;
    };
  }, [tables, projectId, recordType, filters, reloads]);

  const dirtyRows = Object.keys(edits).length;
  useEffect(() => {
    if (dirtyRows === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyRows]);

  const shown = useMemo(() => {
    if (!data) return { context: [] as GridColumn[], editable: [] as GridColumn[] };
    const context = contextKeys
      ? contextKeys.flatMap((key) => data.columns.find((c) => c.key === key) ?? [])
      : data.columns.filter((c) => c.kind === "text").slice(0, 1);
    return { context, editable: data.columns.filter((c) => c.editable && !context.some((x) => x.key === c.key)) };
  }, [data, contextKeys]);

  const setCell = useCallback((row: GridRow, key: string, value: string) => {
    setEdits((current) => {
      const next = { ...current, [row.id]: { ...current[row.id] } };
      if (value === row.cells[key]) delete next[row.id][key];
      else next[row.id][key] = value;
      if (Object.keys(next[row.id]).length === 0) delete next[row.id];
      return next;
    });
    setRowErrors((current) => (row.id in current ? without(current, row.id) : current));
  }, []);

  async function saveAll() {
    if (!data) return;
    setSaving(true);
    const pending = data.rows.filter((r) => edits[r.id]);
    let saved = 0;
    let failed = 0;
    const errors: Record<string, string> = {};
    for (let start = 0; start < pending.length; start += SAVE_CONCURRENCY) {
      await Promise.all(pending.slice(start, start + SAVE_CONCURRENCY).map(async (row) => {
        const cells = edits[row.id];
        const expected = Object.fromEntries(Object.keys(cells).map((key) => [key, row.cells[key]]));
        try {
          const fresh = await tables.saveRow(projectId, recordType, row.code, cells, expected);
          saved += 1;
          setData((current) => current && { ...current, rows: current.rows.map((r) => (r.id === row.id ? fresh : r)) });
          setEdits((current) => without(current, row.id));
        } catch (err) {
          failed += 1;
          errors[row.id] = toErrorMessage(err, "Could not save this row.");
        }
      }));
    }
    setRowErrors(errors);
    setSaving(false);
    showToast(failed ? `${saved} saved, ${failed} failed.` : `${saved} saved.`, failed ? "error" : "success");
    if (saved) onSaved?.();
  }

  function reload() {
    setEdits({});
    setRowErrors({});
    setReloads((n) => n + 1);
  }

  function moveFocus(e: React.KeyboardEvent<HTMLTableCellElement>, key: string, direction: 1 | -1) {
    e.preventDefault();
    let row = e.currentTarget.parentElement?.nextElementSibling ?? null;
    if (direction === -1) row = e.currentTarget.parentElement?.previousElementSibling ?? null;
    while (row) {
      const target = row.querySelector<HTMLElement>(`td[data-grid-col="${key}"] select:not(:disabled), td[data-grid-col="${key}"] input:not(:disabled), td[data-grid-col="${key}"] [tabindex]`);
      if (target) {
        target.focus();
        return;
      }
      row = direction === 1 ? row.nextElementSibling : row.previousElementSibling;
    }
  }

  if (loadError) return <p className="text-muted" role="alert">{loadError}</p>;
  if (data === null) return <Spinner />;
  if (data.rows.length === 0) return <p className="text-muted">No records match these filters.</p>;

  const columnCount = 1 + shown.context.length + shown.editable.length;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <span className="text-muted" role="status">
          {data.truncated
            ? `Showing the first ${data.rows.length} of ${data.total} records. Narrow the filters to see the rest.`
            : `${data.total} ${data.total === 1 ? "record" : "records"}`}
          {!data.can_edit && " · You can view these records but not change them here."}
        </span>
        {data.can_edit && (
          <div className="row">
            <button className="btn" type="button" disabled={dirtyRows === 0 || saving} onClick={() => setEdits({})}>Discard changes</button>
            <button className="btn" type="button" disabled={saving} onClick={() => (dirtyRows ? setConfirmReload(true) : reload())}>Reload</button>
            <button className="btn btn-primary" type="button" disabled={dirtyRows === 0 || saving} onClick={() => void saveAll()}>
              {saving ? "Saving…" : dirtyRows ? `Save ${dirtyRows} ${dirtyRows === 1 ? "change" : "changes"}` : "Save changes"}
            </button>
          </div>
        )}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="record-grid" aria-label={`${data.label} grid`}>
          <thead>
            <tr>
              <th scope="col">Code</th>
              {shown.context.map((c) => <th key={c.key} scope="col">{c.label}</th>)}
              {shown.editable.map((c) => <th key={c.key} scope="col">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <GridRowView
                key={row.id} row={row} context={shown.context} editable={shown.editable} edits={edits[row.id]}
                canEdit={data.can_edit && !saving} columnCount={columnCount} error={rowErrors[row.id]}
                href={recordHref?.(row)} onChange={setCell} onMove={moveFocus}
              />
            ))}
          </tbody>
        </table>
      </div>
      {confirmReload && (
        <ConfirmDialog
          title="Discard unsaved changes?" confirmLabel="Discard and reload"
          message={`${dirtyRows} ${dirtyRows === 1 ? "row has" : "rows have"} changes that are not saved. Reloading shows the saved values and drops them.`}
          onCancel={() => setConfirmReload(false)} onConfirm={() => { setConfirmReload(false); reload(); }}
        />
      )}
    </div>
  );
}

/** One row (and its error row): the code, the context cells, then a control or a locked value per editable column. */
function GridRowView({
  row, context, editable, edits, canEdit, columnCount, error, href, onChange, onMove,
}: {
  row: GridRow;
  context: GridColumn[];
  editable: GridColumn[];
  edits: Record<string, string> | undefined;
  canEdit: boolean;
  columnCount: number;
  error: string | undefined;
  href: string | undefined;
  onChange: (row: GridRow, key: string, value: string) => void;
  onMove: (e: React.KeyboardEvent<HTMLTableCellElement>, key: string, direction: 1 | -1) => void;
}) {
  const rowLocked = !canEdit || row.read_only !== null;
  return (
    <>
      <tr className={row.read_only ? "record-grid__row--read-only" : undefined}>
        <td>
          {href ? <Link to={href}>{row.code}</Link> : row.code}
          {row.read_only && <span className="sr-only"> ({row.read_only})</span>}
        </td>
        {context.map((c) => <td key={c.key}>{row.cells[c.key]}</td>)}
        {editable.map((column) => {
          const value = edits?.[column.key] ?? row.cells[column.key] ?? "";
          const reason = row.read_only ?? row.locks[column.key] ?? null;
          const dirty = edits !== undefined && column.key in edits;
          return (
            <td
              key={column.key} data-grid-col={column.key} className={dirty ? "record-grid__cell--changed" : undefined}
              onKeyDown={(e) => {
                const target = e.target as HTMLElement;
                const isSelect = target.tagName === "SELECT";
                if (e.key === "Enter" && target.tagName !== "BUTTON") onMove(e, column.key, e.shiftKey ? -1 : 1);
                else if (!isSelect && (e.key === "ArrowDown" || e.key === "ArrowUp") && column.kind !== "bool") onMove(e, column.key, e.key === "ArrowDown" ? 1 : -1);
              }}
            >
              {reason || rowLocked ? (
                <LockedValue value={value} reason={reason ?? "You do not have permission to change these records."} />
              ) : (
                <GridCellControl column={column} code={row.code} value={value} onChange={(next) => onChange(row, column.key, next)} />
              )}
            </td>
          );
        })}
      </tr>
      {error && (
        <tr><td colSpan={columnCount} className="record-grid__error" role="alert">{row.code}: {error}</td></tr>
      )}
    </>
  );
}

/** A value that cannot be changed, with the reason in a tooltip; focusable so the reason is reachable by keyboard. */
function LockedValue({ value, reason }: { value: string; reason: string }) {
  return (
    <Tooltip label={reason} wrap>
      <span className="record-grid__locked" tabIndex={0}>
        {value || "–"}
        <span className="sr-only"> ({reason})</span>
      </span>
    </Tooltip>
  );
}

/** The shared control for a column's kind. */
function GridCellControl({
  column, code, value, onChange,
}: {
  column: GridColumn;
  code: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const ariaLabel = `${column.label} for ${code}`;
  if (column.kind === "bool") {
    return <InlineCheckbox ariaLabel={ariaLabel} checked={value === "true"} onChange={(checked) => onChange(checked ? "true" : "false")} />;
  }
  if (column.kind === "date") return <InlineTextInput ariaLabel={ariaLabel} type="date" value={value} onChange={onChange} />;
  if (column.kind === "number") return <InlineTextInput ariaLabel={ariaLabel} type="number" value={value} onChange={onChange} />;
  if (column.kind === "enum" && column.choices) {
    // A value the list no longer offers (a retired type) stays selectable so it is shown, not silently replaced.
    const choices = value && !column.choices.includes(value) ? [value, ...column.choices] : column.choices;
    return (
      <InlineSelect
        ariaLabel={ariaLabel} value={value} onChange={onChange} options={choices.map((c) => ({ value: c, label: c }))}
        placeholder={column.required ? null : "–"}
      />
    );
  }
  return <InlineTextInput ariaLabel={ariaLabel} value={value} onChange={onChange} />;
}
