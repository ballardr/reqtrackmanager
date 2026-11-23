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
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ConfirmDialog } from "./ConfirmDialog";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { CellText } from "./CellText";
import { DefinitionAddModal } from "./DefinitionAddModal";
import { InlineTextInput } from "./FormFields";

const strings = t();

/**
 * One editable text field of a `DefinitionList` row or add form, keyed by `key` into the values passed to
 * `onRename`/`onAdd`.
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
  /** What the field is and affects (from `strings.help`), shown as its `(?)` in the Add dialog; omit for a self-explanatory field. */
  help?: string;
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

/**
 * How the Add button creates an item: `onAdd` takes the values typed in the list's own name-and-fields dialog, and
 * `onAddRequest` hands the button to the caller, which opens its own full form (the one Edit uses) so a type with
 * more attributes than the list shows has one create, not a reduced one beside a full one.
 */
export type DefinitionListAdd =
  | {
    /** Creates the item from the values of the Add dialog (one field per entry of `fields`). */
    onAdd: (values: Record<string, string>) => Promise<void>;
    onAddRequest?: undefined;
  }
  | {
    onAdd?: undefined;
    /** Called when the Add button is pressed; the caller opens its own create dialog. `fields` are then only the columns. */
    onAddRequest: () => void;
  };

export type DefinitionListProps<T extends { id: string }> = DefinitionListBaseProps<T> & DefinitionListAdd;

interface DefinitionListBaseProps<T extends { id: string }> {
  items: T[];
  fields: DefinitionListField<T>[];
  /** Label shown for each candidate in the in-use delete dialog's reassign dropdown. */
  getReassignLabel: (item: T) => string;
  /** Reorders an item. Omit for lists whose order is derived (e.g.
   * scoring levels, ordered by weight) — the reorder buttons are hidden. */
  onMove?: (id: string, direction: "up" | "down") => Promise<void>;
  onRename: (id: string, values: Record<string, string>) => Promise<void>;
  /**
   * Deletes the item. Called first with no `reassignToId`: a plain delete succeeds unless the item is in use, when
   * it throws an `ApiError` with status 409 whose message names the count. `DefinitionList` then opens
   * `DeleteInUseDialog` and calls this again with the chosen `reassignToId`. `keep` is true when the dialog's
   * "keep for other projects" box was ticked (only vocabularies offering it, link types).
   */
  onDelete: (id: string, reassignToId?: string, keep?: boolean) => Promise<void>;
  /**
   * Richer content for the in-use dialog, for a vocabulary whose deletion has more choices than the default (link
   * types: usage counts, replacements that cannot take every link, delete-the-links). Called with the item and the
   * 409 message; omit for the default dialog (every other item as a candidate, labelled by `getReassignLabel`).
   */
  loadInUse?: (item: T, message: string) => Promise<DeleteInUseConfig>;
  deleteLabel: string;
  /** Overrides `deleteLabel` for one row, for a row whose delete means something
   * else (an organisation default that is only hidden in this project). */
  getDeleteLabel?: (item: T) => string;
  /** Asks first (Tier 1) before deleting a row: return the dialog text for the
   * row, or `null` to delete at once. */
  confirmDelete?: (item: T) => { title: string; message: ReactNode; confirmLabel: string } | null;
  /** The Add button's name and the title of the dialog it opens (one field per entry of `fields`); the list shows no empty fields. */
  addLabel: string;
  /**
   * The list's other actions (restoring hidden organisation defaults), as rows of one actions menu beside the Add
   * button; the menu is absent when there are none (docs/ux-style-guide.md, "Pattern: page actions menu").
   */
  menuItems?: ActionMenuItem[];
  /**
   * Per-row slot rendered between the text fields and the reorder/delete buttons, for an attribute the text-only
   * `fields` contract cannot express (a boolean toggle). Omit for the all-text case.
   */
  renderExtra?: (item: T) => ReactNode;
  /**
   * What `renderExtra` shows, which decides its column (`layout="grid"` only). `"text"` (default): a line of
   * user-typed text (a summary), possibly with controls after it; the column is a bounded share of the grid, the
   * text is a `CellText` that is cut and gives way, and controls keep their size and line. `"controls"`: only
   * fixed-size controls (a toggle, a fixed-width select); the column is as wide as they are and they wrap in a
   * narrow container. Record text never goes in a `"controls"` column: its width would follow the longest row.
   */
  extraContent?: "text" | "controls";
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
   * (`DefinitionListField.label`/`track`), rows and the add row aligned under it and row actions in a last
   * column, for several fields or a per-row control (`renderExtra` gets its own column, see `extraContent`; keep
   * its width equal on every row). In a container narrower than 34rem a list with `renderExtra` drops the columns:
   * the extra controls wrap onto the line below the fields and actions. `renderDetails` is ignored in a grid.
   */
  layout?: "stack" | "grid";
}

/**
 * Shared CRUD list for the app's "definition" entities: small, ordered, flat lists of named things (action types,
 * project statuses, link types ...) with inline rename, reorder, add (an Add button opening `DefinitionAddModal`)
 * and a delete-or-reassign-if-in-use flow through `DeleteInUseDialog`.
 */
export function DefinitionList<T extends { id: string }>({
  items,
  fields,
  getReassignLabel,
  onMove,
  onRename,
  onAdd,
  onAddRequest,
  onDelete,
  loadInUse,
  deleteLabel,
  getDeleteLabel,
  confirmDelete,
  addLabel,
  menuItems,
  renderExtra,
  extraContent = "text",
  renderDetails,
  isReadOnly,
  minItems = 1,
  layout = "stack",
}: DefinitionListProps<T>) {
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [adding, setAdding] = useState(false);
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

  /** The list's single Add control: the empty fields live in a dialog, not in the list (creation controls on demand);
   * the list's other actions are rows of the one menu beside it. */
  const addControl = (
    <div className="row" style={{ alignItems: "center" }}>
      <button
        className="btn btn-primary btn--fit" aria-label={addLabel}
        onClick={() => { setError(null); if (onAddRequest) onAddRequest(); else setAdding(true); }}
      >
        <Plus /> <CellText>{addLabel}</CellText>
      </button>
      {menuItems && menuItems.length > 0 && <ActionMenu triggerLabel={strings.recordTables.menuLabel} items={menuItems} />}
    </div>
  );

  const dialogs = (
    <>
      {adding && onAdd && (
        <DefinitionAddModal
          title={addLabel}
          fields={fields}
          onAdd={onAdd}
          onClose={() => setAdding(false)}
        />
      )}
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

  /** A grid cell's control: a one-line input, or a text area that starts at one row and grows with its content;
   * a row is named by its column heading. */
  function gridControl(f: DefinitionListField<T>, value: string, onChange: (next: string) => void, disabled = false) {
    const ariaLabel = f.ariaLabel ?? f.placeholder ?? f.key;
    return f.multiline ? (
      <AutoGrowTextarea plainText="Configuration text shown in pickers and tooltips" rows={1} aria-label={ariaLabel} value={value} onChange={onChange} disabled={disabled} />
    ) : (
      <InlineTextInput type={f.inputType ?? "text"} ariaLabel={ariaLabel} value={value} onChange={onChange} disabled={disabled} />
    );
  }

  if (layout === "grid") {
    const columns = `${fields.map((f) => f.track ?? "minmax(0, 1fr)").join(" ")}${renderExtra ? (extraContent === "text" ? " minmax(14rem, 1.5fr)" : " minmax(0, max-content)") : ""} max-content`; // grid-text-ok: the extra column is bounded for text, and the last column holds only the row's fixed-size buttons
    const floorHint = minItems > 1 ? strings.admin.deleteMinItemsHint(minItems) : strings.admin.deleteLastOneHint;
    return (
      <div className={renderExtra ? "stack definition-list--extra" : "stack"}>
        {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
        {addControl}
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
                    {gridControl(f, draft[f.key], (next) => setEdits((m) => ({ ...m, [item.id]: { ...draft, [f.key]: next } })), readOnly)}
                  </div>
                ))}
                {renderExtra && (
                  <div className={`definition-grid__actions definition-grid__extra definition-grid__extra--${extraContent}`}>{renderExtra(item)}</div>
                )}
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
        </div>
        {dialogs}
      </div>
    );
  }

  return (
    <div className="stack">
      {error && <div style={{ color: "var(--color-danger)" }}>{error}</div>}
      {addControl}
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
                      plainText="Configuration text shown in pickers and tooltips"
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
      {dialogs}
    </div>
  );
}
