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
  addLabel: string;
  /**
   * Optional per-row slot rendered between the text field(s) and the
   * reorder/delete buttons — for a field this component's own text-only
   * `fields` contract can't express (e.g. a boolean toggle). Added for the
   * Compliance Module's mapping-relationship-type vocabulary
   * (`implies_equivalence`, docs/compliance-module-plan.md Phase 12) rather
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
  /** The fewest items the list may hold (default 1); delete is disabled at
   * this floor. Scoring axes, for example, keep at least two levels. */
  minItems?: number;
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
  addLabel,
  renderExtra,
  renderDetails,
  minItems = 1,
}: DefinitionListProps<T>) {
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [newDraft, setNewDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, ""]))
  );
  const [inUse, setInUse] = useState<{ item: T; config: DeleteInUseConfig | null; message: string } | null>(null);
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

  async function handleAdd() {
    setError(null);
    try {
      await onAdd(newDraft);
      setNewDraft(Object.fromEntries(fields.map((f) => [f.key, ""])));
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
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
          <div key={item.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="row">
                {fields.map((f) => (
                  <input
                    key={f.key}
                    className="input"
                    type={f.inputType ?? "text"}
                    style={{ maxWidth: f.maxWidth ?? 220 }}
                    aria-label={f.ariaLabel}
                    value={draft[f.key]}
                    onChange={(e) => setEdits((m) => ({ ...m, [item.id]: { ...draft, [f.key]: e.target.value } }))}
                  />
                ))}
                {dirty && isValid(draft) && (
                  <button className="btn" title={strings.admin.rename} aria-label={strings.admin.rename} onClick={() => handleRename(item)}>
                    <Pencil size={14} />
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
                      <ArrowUp size={14} />
                    </button>
                    <button
                      className="btn"
                      disabled={idx === items.length - 1}
                      title={strings.common.down}
                      aria-label={strings.common.down}
                      onClick={() => onMove(item.id, "down")}
                    >
                      <ArrowDown size={14} />
                    </button>
                  </>
                )}
                <button
                  className="btn btn-danger"
                  disabled={atFloor}
                  title={atFloor ? floorHint : deleteLabel}
                  aria-label={atFloor ? floorHint : deleteLabel}
                  onClick={() => handleAttemptDelete(item)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            {renderDetails?.(item)}
          </div>
        );
      })}
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
      <div className="row">
        {fields.map((f) => (
          <input
            key={f.key}
            className="input"
            type={f.inputType ?? "text"}
            placeholder={f.placeholder}
            aria-label={fields.length > 1 ? f.ariaLabel : undefined}
            value={newDraft[f.key]}
            onChange={(e) => setNewDraft((d) => ({ ...d, [f.key]: e.target.value }))}
          />
        ))}
        <button className="btn btn-primary" onClick={handleAdd} disabled={!isValid(newDraft)}>
          <Plus size={14} /> {addLabel}
        </button>
      </div>
    </div>
  );
}
