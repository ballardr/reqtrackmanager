import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { t } from "../i18n/strings";
import {
  DeleteInUseDialog,
  type DeleteInUseCandidate,
  type DeleteInUseKeepOption,
  type DeleteInUseRemoveOption,
} from "./DeleteInUseDialog";
import { ConfirmDialog } from "./ConfirmDialog";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { InlineTextInput, TextAreaField, TextField } from "./FormFields";

const strings = t();

/**
 * One editable text field of a `DefinitionList` row/add-form, keyed by
 * `key` into the `Record<string, string>` values passed to `onRename`/`onAdd`.
 */
export interface DefinitionListField<T> {
  key: string;
  getValue: (item: T) => string;
  placeholder?: string;
  ariaLabel?: string;
  maxWidth?: number;
  /** Allows a blank value (default: every field is required). */
  optional?: boolean;
  /** HTML input type; `"number"` for numeric fields such as a scoring
   * level's weight (default `"text"`). */
  inputType?: "text" | "number";
  /** A long free-text value (a definition): a row shows a field that grows with its content, and the add form a
   * growing text area, instead of a one-line input. */
  multiline?: boolean;
  /** `layout="grid"` only: the column heading (default: the placeholder). */
  label?: string;
  /** `layout="grid"` only: the column's CSS grid track (default `minmax(0, 1fr)`), e.g. `"6rem"`. */
  track?: string;
}

/** What the in-use delete dialog shows for one item, when a vocabulary needs
 * more than the default "move to another one" (see `loadInUse`). */
export interface DeleteInUseConfig {
  summary?: ReactNode;
  details?: string[];
  candidates: DeleteInUseCandidate[];
  remove?: DeleteInUseRemoveOption;
  /** Offer to leave the item behind for the other projects that use it (ticked by default). */
  keep?: DeleteInUseKeepOption;
  /** Reassesses the dialog for the box being ticked or not (candidates depend on what would still move). */
  reload?: (keep: boolean) => Promise<DeleteInUseConfig>;
  /** Why moving is unavailable; set to disable it. */
  moveBlockedReason?: string;
}

export interface DefinitionListProps<T extends { id: string }> {
  items: T[];
  fields: DefinitionListField<T>[];
  /** Label shown for each candidate in the in-use delete dialog's reassign dropdown. */
  getReassignLabel: (item: T) => string;
  /** Reorders an item. Omit for lists whose order is derived (e.g.
   * scoring levels, ordered by weight) — the reorder buttons are hidden. */
  onMove?: (id: string, direction: "up" | "down") => Promise<void>;
  onRename: (id: string, values: Record<string, string>) => Promise<void>;
  onAdd: (values: Record<string, string>) => Promise<void>;
  /**
   * Deletes the item. Called first with no `reassignToId` — per the
   * shared server contract, a plain delete succeeds unless the item is
   * in use, in which case it throws an `ApiError` with status 409 whose
   * message names the conflicting count. `DefinitionList` catches that
   * and opens `DeleteInUseDialog`, then calls this again with the chosen
   * `reassignToId`. `keep` is true when the dialog's "keep for other
   * projects" box was ticked (only vocabularies offering it, link types).
   */
  onDelete: (id: string, reassignToId?: string, keep?: boolean) => Promise<void>;
  /**
   * Optional richer content for the in-use dialog, for a vocabulary whose
   * deletion has more to say or more choices than the default (link types:
   * usage counts, replacements that cannot take every link, delete-the-links).
   * Called with the item and the 409 message; omit for the default dialog
   * (every other item as a candidate, labelled by `getReassignLabel`).
   */
  loadInUse?: (item: T, message: string) => Promise<DeleteInUseConfig>;
  deleteLabel: string;
  /** Overrides `deleteLabel` for one row, for a row whose delete means something
   * else (an organisation default that is only hidden in this project). */
  getDeleteLabel?: (item: T) => string;
  /** Asks first (Tier 1) before deleting a row: return the dialog text for the
   * row, or `null` to delete at once. */
  confirmDelete?: (item: T) => { title: string; message: ReactNode; confirmLabel: string } | null;
  addLabel: string;
  /**
   * Optional per-row slot rendered between the text field(s) and the
   * reorder/delete buttons — for a field this component's own text-only
   * `fields` contract can't express (e.g. a boolean toggle). Added for the
   * Compliance Module's mapping-relationship-type vocabulary
   * (`implies_equivalence`) rather
   * than bolting a boolean-specific field type onto `DefinitionListField`
   * itself — a generic escape hatch here benefits any future "definition"
   * entity with one extra non-text attribute, not just this one caller.
   * Omit for the common all-text case (every pre-existing call site).
   */
  renderExtra?: (item: T) => ReactNode;
  /** Optional per-row slot rendered on its own line under the row — for a
   * group of controls too wide for the row itself (link types'
   * "can link from/to" restrictions). */
  renderDetails?: (item: T) => ReactNode;
  /** `layout="grid"` only: a row whose fields cannot be renamed here (an organisation default shown in a project,
   * which that project can only hide); its inputs are unavailable and no rename button appears. */
  isReadOnly?: (item: T) => boolean;
  /** The fewest items the list may hold (default 1); delete is disabled at
   * this floor. Scoring axes, for example, keep at least two levels. */
  minItems?: number;
  /**
   * `"stack"` (default): each row is a line of unlabelled inputs. `"grid"`: one CSS grid with a heading per field
   * (`DefinitionListField.label`/`track`), every row and the add row aligned under it and the row actions in a
   * last column, for a list of several fields (a scoring level's name, weight and guidance) or one with a per-row
   * control beside the fields (`renderExtra` gets its own right-aligned column; keep its width the same on every
   * row so the controls line up). `renderDetails` is ignored in a grid.
   */
  layout?: "stack" | "grid";
}

/**
 * Shared CRUD list for the app's "definition" entities — small, ordered,
 * flat lists of named things (action types, project statuses, link
 * types, ...) that support inline rename, reorder, add, and a
 * delete-or-reassign-if-in-use flow, the latter through the shared
 * `DeleteInUseDialog`. Consolidates what were three near-identical
 * implementations of the same rename/reorder/delete logic in
 * `ProjectAdminPage`/`OrgAdminPage`.
 */
export function DefinitionList<T extends { id: string }>({
  items,
  fields,
  getReassignLabel,
  onMove,
  onRename,
  onAdd,
  onDelete,
  loadInUse,
  deleteLabel,
  getDeleteLabel,
  confirmDelete,
  addLabel,
  renderExtra,
  renderDetails,
  isReadOnly,
  minItems = 1,
  layout = "stack",
}: DefinitionListProps<T>) {
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [newDraft, setNewDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, ""]))
  );
  const [inUse, setInUse] = useState<{ item: T; config: DeleteInUseConfig | null; message: string } | null>(null);
  const [confirming, setConfirming] = useState<{ item: T; title: string; message: ReactNode; confirmLabel: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  function draftFor(item: T): Record<string, string> {
    return edits[item.id] ?? Object.fromEntries(fields.map((f) => [f.key, f.getValue(item)]));
  }
  function isDirty(item: T, draft: Record<string, string>) {
    return fields.some((f) => draft[f.key] !== f.getValue(item));
  }
  function isValid(draft: Record<string, string>) {
    return fields.every((f) => f.optional || draft[f.key].trim() !== "");
  }

  async function handleRename(item: T) {
    setError(null);
    try {
      await onRename(item.id, draftFor(item));
      setEdits((m) => {
        const next = { ...m };
        delete next[item.id];
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  async function handleAttemptDelete(item: T) {
    setError(null);
    try {
      await onDelete(item.id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        try {
          // Without `loadInUse` the candidates are read live from `items` at render, so a rename that
          // lands while the dialog is open shows the new name rather than a stale snapshot.
          const config = loadInUse ? await loadInUse(item, err.message) : null;
          setInUse({ item, config, message: err.message });
        } catch (loadErr) {
          setError(loadErr instanceof Error ? loadErr.message : strings.common.error);
        }
      } else {
        setError(err instanceof Error ? err.message : strings.common.error);
      }
    }
  }

  function handleDeleteClick(item: T) {
    const confirm = confirmDelete?.(item) ?? null;
    if (confirm) setConfirming({ item, ...confirm });
    else void handleAttemptDelete(item);
  }

  async function handleAdd() {
    setError(null);
    try {
      await onAdd(newDraft);
      setNewDraft(Object.fromEntries(fields.map((f) => [f.key, ""])));
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  const dialogs = (
    <>
      {confirming && (
        <ConfirmDialog
          title={confirming.title}
          message={confirming.message}
          confirmLabel={confirming.confirmLabel}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const { item } = confirming;
            setConfirming(null);
            void handleAttemptDelete(item);
          }}
        />
      )}
      {inUse && (
        <DeleteInUseDialog
          title={strings.admin.deleteInUseTitle(fields[0].getValue(inUse.item))}
          summary={inUse.config?.summary ?? inUse.message}
          details={inUse.config?.details}
          candidates={
            inUse.config?.candidates ??
            items
              .filter((other) => other.id !== inUse.item.id)
              .map((other) => ({ id: other.id, label: getReassignLabel(other) }))
          }
          onMove={(replacementId, keep) => onDelete(inUse.item.id, replacementId, keep)}
          remove={inUse.config?.remove}
          keep={inUse.config?.keep}
          moveBlockedReason={inUse.config?.moveBlockedReason}
          onKeepChange={
            inUse.config?.reload
              ? async (keep) => {
                  const config = await inUse.config!.reload!(keep);
                  setInUse((current) => (current ? { ...current, config } : current));
                }
              : undefined
          }
          onDeleteKeeping={inUse.config?.keep ? () => onDelete(inUse.item.id, undefined, true) : undefined}
          onClose={() => setInUse(null)}
        />
      )}
    </>
  );

  /** A grid cell's control: a one-line input, or a text area that starts at one row and grows with its content.
   * Only the add row shows the placeholder; an existing row is named by its column heading. */
  function gridControl(
    f: DefinitionListField<T>, value: string, onChange: (next: string) => void, adding = false, disabled = false,
  ) {
    // The add row keeps the name it always had (its placeholder, except for a one-line field among several, which
    // takes its aria label), so a row's control and the add row's are told apart by name.
    const addName = f.multiline || fields.length === 1 ? f.placeholder : f.ariaLabel;
    const ariaLabel = adding ? (addName ?? f.ariaLabel ?? f.key) : (f.ariaLabel ?? f.placeholder ?? f.key);
    const placeholder = adding ? f.placeholder : undefined;
    return f.multiline ? (
      <AutoGrowTextarea rows={1} aria-label={ariaLabel} placeholder={placeholder} value={value} onChange={onChange} disabled={disabled} />
    ) : (
      <InlineTextInput type={f.inputType ?? "text"} ariaLabel={ariaLabel} placeholder={placeholder} value={value} onChange={onChange} disabled={disabled} />
    );
  }

  if (layout === "grid") {
    const columns = `${fields.map((f) => f.track ?? "minmax(0, 1fr)").join(" ")}${renderExtra ? " max-content" : ""} max-content`;
    const floorHint = minItems > 1 ? strings.admin.deleteMinItemsHint(minItems) : strings.admin.deleteLastOneHint;
    return (
      <div className="stack">
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        <div className="definition-grid" style={{ gridTemplateColumns: columns }}>
          {fields.map((f) => <span key={f.key} className="definition-grid__head">{f.label ?? f.placeholder ?? f.key}</span>)}
          {renderExtra && <span aria-hidden="true" className="definition-grid__head" />}
          <span aria-hidden="true" className="definition-grid__head" />
          {items.map((item, idx) => {
            const draft = draftFor(item);
            const readOnly = isReadOnly?.(item) ?? false;
            const dirty = !readOnly && isDirty(item, draft);
            const atFloor = items.length <= minItems;
            return (
              <div key={item.id} className="definition-grid__row">
                {fields.map((f) => (
                  <div key={f.key} className="definition-grid__cell">
                    {gridControl(f, draft[f.key], (next) => setEdits((m) => ({ ...m, [item.id]: { ...draft, [f.key]: next } })), false, readOnly)}
                  </div>
                ))}
                {renderExtra && <div className="definition-grid__actions">{renderExtra(item)}</div>}
                <div className="definition-grid__actions">
                  {/* Always laid out so the columns do not shift when a row becomes dirty; hidden (and out of
                      the accessibility tree) until there is something to save. */}
                  <button
                    className="btn" title={strings.admin.rename} aria-label={strings.admin.rename}
                    style={{ visibility: dirty && isValid(draft) ? "visible" : "hidden" }} onClick={() => handleRename(item)}
                  >
                    <Pencil />
                  </button>
                  {onMove && (
                    <>
                      <button className="btn" disabled={idx === 0} title={strings.common.up} aria-label={strings.common.up} onClick={() => onMove(item.id, "up")}>
                        <ArrowUp />
                      </button>
                      <button
                        className="btn" disabled={idx === items.length - 1} title={strings.common.down} aria-label={strings.common.down}
                        onClick={() => onMove(item.id, "down")}
                      >
                        <ArrowDown />
                      </button>
                    </>
                  )}
                  <button
                    className="btn btn-danger" disabled={atFloor}
                    title={atFloor ? floorHint : (getDeleteLabel?.(item) ?? deleteLabel)}
                    aria-label={atFloor ? floorHint : (getDeleteLabel?.(item) ?? deleteLabel)}
                    onClick={() => handleDeleteClick(item)}
                  >
                    <Trash2 />
                  </button>
                </div>
              </div>
            );
          })}
          {fields.map((f) => (
            <div key={`add-${f.key}`} className="definition-grid__cell definition-grid__add">
              {gridControl(f, newDraft[f.key], (next) => setNewDraft((d) => ({ ...d, [f.key]: next })), true)}
            </div>
          ))}
          {renderExtra && <div className="definition-grid__add" />}
          <div className="definition-grid__actions definition-grid__add">
            <button className="btn btn-primary" title={addLabel} aria-label={addLabel} onClick={handleAdd} disabled={!isValid(newDraft)}>
              <Plus /> Add
            </button>
          </div>
        </div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="stack">
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      {items.map((item, idx) => {
        const draft = draftFor(item);
        const dirty = isDirty(item, draft);
        const atFloor = items.length <= minItems;
        const floorHint = minItems > 1 ? strings.admin.deleteMinItemsHint(minItems) : strings.admin.deleteLastOneHint;
        return (
          <div key={item.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-3)" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="row">
                {fields.map((f) =>
                  f.multiline ? (
                    <AutoGrowTextarea
                      key={f.key}
                      rows={2}
                      style={{ width: f.maxWidth ?? 360, maxWidth: "100%" }}
                      aria-label={f.ariaLabel ?? f.placeholder ?? f.key}
                      placeholder={f.placeholder}
                      value={draft[f.key]}
                      onChange={(next) => setEdits((m) => ({ ...m, [item.id]: { ...draft, [f.key]: next } }))}
                    />
                  ) : (
                    <InlineTextInput
                      key={f.key}
                      type={f.inputType ?? "text"}
                      maxWidth={f.maxWidth ?? 220}
                      ariaLabel={f.ariaLabel ?? f.placeholder ?? f.key}
                      value={draft[f.key]}
                      onChange={(next) => setEdits((m) => ({ ...m, [item.id]: { ...draft, [f.key]: next } }))}
                    />
                  )
                )}
                {dirty && isValid(draft) && (
                  <button className="btn" title={strings.admin.rename} aria-label={strings.admin.rename} onClick={() => handleRename(item)}>
                    <Pencil />
                  </button>
                )}
              </div>
              <div className="row">
                {renderExtra?.(item)}
                {onMove && (
                  <>
                    <button
                      className="btn"
                      disabled={idx === 0}
                      title={strings.common.up}
                      aria-label={strings.common.up}
                      onClick={() => onMove(item.id, "up")}
                    >
                      <ArrowUp />
                    </button>
                    <button
                      className="btn"
                      disabled={idx === items.length - 1}
                      title={strings.common.down}
                      aria-label={strings.common.down}
                      onClick={() => onMove(item.id, "down")}
                    >
                      <ArrowDown />
                    </button>
                  </>
                )}
                <button
                  className="btn btn-danger"
                  disabled={atFloor}
                  title={atFloor ? floorHint : (getDeleteLabel?.(item) ?? deleteLabel)}
                  aria-label={atFloor ? floorHint : (getDeleteLabel?.(item) ?? deleteLabel)}
                  onClick={() => handleDeleteClick(item)}
                >
                  <Trash2 />
                </button>
              </div>
            </div>
            {renderDetails?.(item)}
          </div>
        );
      })}
      {confirming && (
        <ConfirmDialog
          title={confirming.title}
          message={confirming.message}
          confirmLabel={confirming.confirmLabel}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const { item } = confirming;
            setConfirming(null);
            void handleAttemptDelete(item);
          }}
        />
      )}
      {inUse && (
        <DeleteInUseDialog
          title={strings.admin.deleteInUseTitle(fields[0].getValue(inUse.item))}
          summary={inUse.config?.summary ?? inUse.message}
          details={inUse.config?.details}
          candidates={
            inUse.config?.candidates ??
            items
              .filter((other) => other.id !== inUse.item.id)
              .map((other) => ({ id: other.id, label: getReassignLabel(other) }))
          }
          onMove={(replacementId, keep) => onDelete(inUse.item.id, replacementId, keep)}
          remove={inUse.config?.remove}
          keep={inUse.config?.keep}
          moveBlockedReason={inUse.config?.moveBlockedReason}
          onKeepChange={
            inUse.config?.reload
              ? async (keep) => {
                  const config = await inUse.config!.reload!(keep);
                  setInUse((current) => (current ? { ...current, config } : current));
                }
              : undefined
          }
          onDeleteKeeping={inUse.config?.keep ? () => onDelete(inUse.item.id, undefined, true) : undefined}
          onClose={() => setInUse(null)}
        />
      )}
      <div className="row" style={{ alignItems: "flex-end" }}>
        {fields.map((f) =>
          f.multiline ? (
            <TextAreaField helpNotNeeded
              key={f.key}
              label={f.placeholder ?? f.ariaLabel ?? f.key}
              value={newDraft[f.key]}
              onChange={(next) => setNewDraft((d) => ({ ...d, [f.key]: next }))}
            />
          ) : (
            <TextField helpNotNeeded
              key={f.key}
              label={f.placeholder ?? f.ariaLabel ?? f.key}
              ariaLabel={fields.length > 1 ? f.ariaLabel : undefined}
              placeholder={f.placeholder}
              value={newDraft[f.key]}
              onChange={(next) => setNewDraft((d) => ({ ...d, [f.key]: next }))}
              inputProps={{ type: f.inputType ?? "text" }}
            />
          )
        )}
        <button className="btn btn-primary" onClick={handleAdd} disabled={!isValid(newDraft)}>
          <Plus /> {addLabel}
        </button>
      </div>
    </div>
  );
}
