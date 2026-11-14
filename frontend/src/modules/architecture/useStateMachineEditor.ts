/**
 * Module: modules/architecture/useStateMachineEditor
 *
 * The state machine diagram editor's state for one diagram: the model read from the server, the drawing being edited with
 * its undo/redo history, and the calls that store changes. The pure parts are in `stateMachineModel`; this hook adds
 * loading, saving and conflict handling.
 *
 * Responsibilities:
 * - Load the model (diagram, states, transitions, findings) and read it again after a stored change, merging the result into
 *   the unsaved drawing so nothing is lost.
 * - Save the drawing (`save`), which quotes the diagram's `version`; a stale version sets `conflict` so the page offers a
 *   reload instead of overwriting a newer save.
 * - Run the writes that are stored at once (`write`: add or edit a state, add, edit or delete a transition, change the
 *   diagram's fields): each quotes the current version and is followed by a read, so the findings and counts are current.
 *
 * Design decisions:
 * - Only the drawing (positions, sizes, nesting, attach points) is local until Save, as in the block diagram editor. A
 *   state's or transition's content is stored when its form is saved, because the findings depend on it and because a state
 *   needs its code, which only the server gives.
 * - The server answers a stale version and a refused move (for example an activation with errors) with the same status; only
 *   the stale version is a conflict, told apart by its message, so a refusal never offers to discard the person's work.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { toErrorMessage } from "../../context/ToastContext";
import { projectStateMachineApi } from "./api";
import {
  EMPTY_STATE_LAYOUT, commit, isDirty, layoutFromModel, layoutSignature, layoutToSave, mergeModel, redo, refreshPresent, startHistory,
  undo, type History, type StateMachineLayout,
} from "./stateMachineModel";
import type { ArchitectureRecordStatus, StateMachineFieldValues, StateMachineModel } from "./types";

/** The message the server gives a save based on an older version. */
const STALE_MESSAGE = "This record was changed by someone else";

/** @param error What a call threw. @returns True when it is a stale-version refusal (a newer save exists). */
export function isStaleVersion(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.message.startsWith(STALE_MESSAGE);
}

export interface StateMachineEditor {
  /** The model as read; null until loaded. */
  model: StateMachineModel | null;
  layout: StateMachineLayout;
  loadError: string | null;
  /** The last refusal from a store call that is not a conflict, or null. */
  saveError: string | null;
  /** True once another save advanced the diagram; the page offers to reload. */
  conflict: boolean;
  saving: boolean;
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  /** Applies an edit to the drawing as one undo step. */
  edit: (change: (layout: StateMachineLayout) => StateMachineLayout) => void;
  undo: () => void;
  redo: () => void;
  /** Stores the drawing; resolves true when stored. */
  save: () => Promise<boolean>;
  /**
   * Runs a write that is stored at once, quoting the diagram's current version, then reads the model again. Resolves the
   * call's result, or null when it was refused (the refusal is in `saveError`, a stale version in `conflict`).
   */
  write: <T>(call: (version: number) => Promise<T>) => Promise<T | null>;
  /** Edits the diagram's own fields; resolves true when stored. */
  updateFields: (values: Partial<StateMachineFieldValues>) => Promise<boolean>;
  /** Moves the diagram to another status; resolves true when stored (a refusal is in `saveError`). */
  setStatus: (status: ArchitectureRecordStatus) => Promise<boolean>;
  /** Reads the model again; `discard` also drops unsaved drawing changes. */
  reload: (discard?: boolean) => Promise<void>;
  /** Clears the last refusal. */
  clearError: () => void;
}

/**
 * @param projectId The diagram's project.
 * @param diagramId The state machine diagram.
 */
export function useStateMachineEditor(projectId: string, diagramId: string): StateMachineEditor {
  const api = useMemo(() => projectStateMachineApi(projectId), [projectId]);
  const [model, setModel] = useState<StateMachineModel | null>(null);
  const [history, setHistory] = useState<History>(() => startHistory(EMPTY_STATE_LAYOUT));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const request = useRef(0);
  const loaded = useRef(false);

  // The drawing as last rendered, so a read that resolves later can tell whether an edit was made while it was in flight.
  const latest = useRef(history.present);
  useEffect(() => { latest.current = history.present; });

  /**
   * Reads the model. `discard` true replaces the drawing with the stored one; false merges the stored model into it; a layout
   * is the one just saved: it replaces the drawing only when no edit has been made since, and otherwise becomes the saved
   * baseline, so work done while the read was in flight is kept and only that work stays unsaved.
   */
  const read = useCallback((discard: boolean | StateMachineLayout): Promise<void> => {
    const mine = ++request.current;
    return api.model(diagramId)
      .then((data) => {
        if (mine !== request.current) return;
        setModel(data);
        setLoadError(null);
        const justSaved = typeof discard === "object" ? discard : null;
        const replace = discard === true || !loaded.current
          || (justSaved !== null && layoutSignature(latest.current) === layoutSignature(justSaved));
        if (replace) {
          setHistory(startHistory(layoutFromModel(data)));
          setConflict(false);
        } else {
          setHistory((h) => {
            const merged = refreshPresent(h, mergeModel(h.present, data));
            return justSaved ? { ...merged, saved: justSaved } : { ...merged, saved: mergeModel(h.saved, data) };
          });
        }
        loaded.current = true;
      })
      .catch((err) => {
        if (mine === request.current) setLoadError(toErrorMessage(err, "This state machine diagram could not be found, or you do not have access to it."));
      });
  }, [api, diagramId]);

  useEffect(() => {
    loaded.current = false;
    void read(false);
  }, [read]);

  /** Runs a store call, sorting a refusal into a conflict (a newer save exists) or a message. */
  const store = useCallback(async <T,>(call: (version: number) => Promise<T>): Promise<T | null> => {
    if (!model) return null;
    setSaving(true);
    setSaveError(null);
    try {
      return await call(model.diagram.version);
    } catch (err) {
      if (isStaleVersion(err)) setConflict(true);
      else setSaveError(toErrorMessage(err, "Could not save the state machine diagram."));
      return null;
    } finally {
      setSaving(false);
    }
  }, [model]);

  const save = useCallback(async () => {
    const sent = history.present;
    const { states, transitions } = layoutToSave(sent);
    if ((await store((version) => api.saveLayout(diagramId, version, states, transitions))) === null) return false;
    // The stored drawing is the baseline at once: the read-back may be overtaken by a later read, which must not leave the
    // saved drawing looking unsaved.
    setHistory((h) => ({ ...h, saved: sent }));
    await read(sent);
    return true;
  }, [store, read, api, diagramId, history.present]);

  const write = useCallback(async <T,>(call: (version: number) => Promise<T>): Promise<T | null> => {
    const result = await store(call);
    if (result !== null) await read(false);
    return result;
  }, [store, read]);

  const updateFields = useCallback(
    async (values: Partial<StateMachineFieldValues>) => (await write((version) => api.update(diagramId, version, values))) !== null,
    [write, api, diagramId],
  );

  const setStatus = useCallback(
    async (status: ArchitectureRecordStatus) => (await write((version) => api.setStatus(diagramId, version, status))) !== null,
    [write, api, diagramId],
  );

  return {
    model, layout: history.present, loadError, saveError, conflict, saving,
    dirty: isDirty(history), canUndo: history.past.length > 0, canRedo: history.future.length > 0,
    edit: (change) => setHistory((h) => commit(h, change(h.present))),
    undo: () => setHistory(undo),
    redo: () => setHistory(redo),
    save, write, updateFields, setStatus,
    reload: (discard = false) => read(discard),
    clearError: () => setSaveError(null),
  };
}
