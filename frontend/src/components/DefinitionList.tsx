import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import { t } from "../i18n/strings";

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
}

export interface DefinitionListProps<T extends { id: string }> {
  items: T[];
  fields: DefinitionListField<T>[];
  /** Label shown for each candidate in the reassign-on-delete dropdown. */
  getReassignLabel: (item: T) => string;
  onMove: (id: string, direction: "up" | "down") => Promise<void>;
  onRename: (id: string, values: Record<string, string>) => Promise<void>;
  onAdd: (values: Record<string, string>) => Promise<void>;
  /**
   * Deletes the item. Called first with no `reassignToId` — per the
   * shared server contract, a plain delete succeeds unless the item is
   * in use, in which case it throws an `ApiError` with status 409 whose
   * message names the conflicting count. `DefinitionList` catches that
   * and opens its own reassign-target picker, then calls this again
   * with the chosen `reassignToId`.
   */
  onDelete: (id: string, reassignToId?: string) => Promise<void>;
  deleteLabel: string;
  addLabel: string;
}

/**
 * Shared CRUD list for the app's "definition" entities — small, ordered,
 * flat lists of named things (action types, project statuses, link
 * types, ...) that support inline rename, reorder, add, and a
 * delete-or-reassign-if-in-use flow. Consolidates what were three
 * near-identical implementations of the same rename/reorder/delete
 * logic in `ProjectAdminPage`/`OrgAdminPage`.
 */
export function DefinitionList<T extends { id: string }>({
  items,
  fields,
  getReassignLabel,
  onMove,
  onRename,
  onAdd,
  onDelete,
  deleteLabel,
  addLabel,
}: DefinitionListProps<T>) {
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [newDraft, setNewDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, ""]))
  );
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [inUseMessage, setInUseMessage] = useState<string | null>(null);
  const [reassignTo, setReassignTo] = useState("");
  const [error, setError] = useState<string | null>(null);

  function draftFor(item: T): Record<string, string> {
    return edits[item.id] ?? Object.fromEntries(fields.map((f) => [f.key, f.getValue(item)]));
  }
  function isDirty(item: T, draft: Record<string, string>) {
    return fields.some((f) => draft[f.key] !== f.getValue(item));
  }
  function isValid(draft: Record<string, string>) {
    return fields.every((f) => draft[f.key].trim() !== "");
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
        setDeletingId(item.id);
        setInUseMessage(err.message);
      } else {
        setError(err instanceof Error ? err.message : strings.common.error);
      }
    }
  }

  async function handleConfirmDelete(item: T) {
    if (!reassignTo) return;
    setError(null);
    try {
      await onDelete(item.id, reassignTo);
      setDeletingId(null);
      setInUseMessage(null);
      setReassignTo("");
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
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
        const others = items.filter((other) => other.id !== item.id);
        return (
          <div key={item.id} className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <div className="row">
                {fields.map((f) => (
                  <input
                    key={f.key}
                    className="input"
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
                <button
                  className="btn btn-danger"
                  disabled={others.length === 0}
                  title={others.length === 0 ? strings.admin.deleteLastOneHint : deleteLabel}
                  aria-label={others.length === 0 ? strings.admin.deleteLastOneHint : deleteLabel}
                  onClick={() => handleAttemptDelete(item)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            {deletingId === item.id && (
              <div className="row" style={{ background: "var(--color-surface-alt)", padding: "0.5rem", borderRadius: 6 }}>
                <span>{inUseMessage}</span>
                <span>{strings.admin.reassignExistingTo}</span>
                <select className="input" style={{ maxWidth: 220 }} value={reassignTo} onChange={(e) => setReassignTo(e.target.value)}>
                  <option value="">—</option>
                  {others.map((other) => (
                    <option key={other.id} value={other.id}>{getReassignLabel(other)}</option>
                  ))}
                </select>
                <button className="btn btn-danger" disabled={!reassignTo} onClick={() => handleConfirmDelete(item)}>
                  {strings.admin.confirmDelete}
                </button>
                <button className="btn" onClick={() => { setDeletingId(null); setInUseMessage(null); setReassignTo(""); }}>
                  {strings.common.cancel}
                </button>
              </div>
            )}
          </div>
        );
      })}
      <div className="row">
        {fields.map((f) => (
          <input
            key={f.key}
            className="input"
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
