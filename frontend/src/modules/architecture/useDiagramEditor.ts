/**
 * Module: modules/architecture/useDiagramEditor
 *
 * The diagram editor's state for one diagram: the record, the view read from the server, the model data its lines are
 * resolved from, the layout being edited with its undo/redo history, and the calls that store it. The pure parts are in
 * `diagramEditorModel` and `diagramLines`; this hook adds loading, saving and conflict handling.
 *
 * Responsibilities:
 * - Load the diagram, its view (boxes, notes, view switches) and its model, and read them again after a stored change,
 *   merging the result into the unsaved layout (nothing is lost). Flipping a view switch needs no read: the page works
 *   out the lines from the model.
 * - Save the layout, the toggles and the connection-detail switch, each quoting the diagram's `version`; a 409 sets
 *   `conflict` so the page can offer to reload instead of overwriting a newer save.
 *
 * Design decisions:
 * - Layout edits are local until Save (one undo step per move, resize, add, removal or note edit). Toggles and the
 *   connection-detail switch are stored when changed, since they are settings of the diagram, not drawing edits; they
 *   advance the same version, which this hook keeps current so a later layout save is not stale by its own doing.
 * - A save clears the undo history: the stored layout becomes the new baseline, and notes take their stored ids. An edit
 *   made while the saved layout is being read back is kept (and stays unsaved) instead of being replaced.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { toErrorMessage } from "../../context/ToastContext";
import { projectDiagramApi } from "./api";
import {
  EMPTY_LAYOUT, commit, isDirty, layoutFromView, layoutToSave, mergeView, redo, refreshPresent, startHistory, undo,
  type EditorLayout, type History,
} from "./diagramEditorModel";
import type { ArchitectureDiagram, DiagramFieldValues, DiagramModel, DiagramToggleValues, DiagramView } from "./types";

export interface DiagramEditor {
  diagram: ArchitectureDiagram | null;
  view: DiagramView | null;
  /** The data lines are resolved from; null until loaded. */
  model: DiagramModel | null;
  layout: EditorLayout;
  loadError: string | null;
  /** The last refusal from a store call that is not a conflict, or null. */
  saveError: string | null;
  /** True once another save advanced the diagram; the page offers to reload. */
  conflict: boolean;
  saving: boolean;
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  /** Applies an edit to the layout as one undo step. */
  edit: (change: (layout: EditorLayout) => EditorLayout) => void;
  undo: () => void;
  redo: () => void;
  /** Stores the layout; resolves true when stored. */
  save: () => Promise<boolean>;
  /** Stores the toggles (their rules and members); resolves true when stored. */
  saveToggles: (toggles: DiagramToggleValues[]) => Promise<boolean>;
  /** Edits the diagram's own fields (name, purpose, scope, connection detail); resolves true when stored. */
  updateFields: (values: Partial<DiagramFieldValues>) => Promise<boolean>;
  /** Reads the diagram again; `discard` also drops unsaved layout changes. */
  reload: (discard?: boolean) => Promise<void>;
  /** Reads only the model data (after an element or connection was created elsewhere on the page). */
  reloadModel: () => Promise<void>;
  /** Replaces the record (after a status change or archive made outside the editor). */
  setDiagram: (diagram: ArchitectureDiagram) => void;
}

/** @param layout A layout. @returns What a save of it would send, as text, for telling whether it changed. */
const signatureOf = (layout: EditorLayout): string => JSON.stringify(layoutToSave(layout));

/**
 * @param projectId The diagram's project.
 * @param diagramId The diagram.
 */
export function useDiagramEditor(projectId: string, diagramId: string): DiagramEditor {
  const api = useMemo(() => projectDiagramApi(projectId), [projectId]);
  const [diagram, setDiagramState] = useState<ArchitectureDiagram | null>(null);
  const [view, setView] = useState<DiagramView | null>(null);
  const [model, setModel] = useState<DiagramModel | null>(null);
  const [history, setHistory] = useState<History>(() => startHistory(EMPTY_LAYOUT));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const request = useRef(0);
  const loaded = useRef(false);

  // The layout as last rendered, so a read that resolves later can tell whether an edit was made while it was in flight.
  const latest = useRef(history.present);
  useEffect(() => { latest.current = history.present; });

  /**
   * Reads the diagram again. `discard` true replaces the layout with the stored one; false merges the stored view into it;
   * a layout is the one just saved: it replaces the editor's layout only when no edit has been made since, and otherwise
   * becomes the saved baseline, so work done while the read was in flight is kept and only that work stays unsaved.
   */
  const read = useCallback((discard: boolean | EditorLayout): Promise<void> => {
    const mine = ++request.current;
    return Promise.all([api.get(diagramId), api.view(diagramId), api.model(diagramId)])
      .then(([record, resolved, data]) => {
        if (mine !== request.current) return;
        setDiagramState(record);
        setView(resolved);
        setModel(data);
        setLoadError(null);
        const justSaved = typeof discard === "object" ? discard : null;
        const replace = discard === true || !loaded.current || (justSaved !== null && signatureOf(latest.current) === signatureOf(justSaved));
        if (replace) {
          setHistory(startHistory(layoutFromView(resolved)));
          setConflict(false);
        } else {
          setHistory((h) => {
            const merged = refreshPresent(h, mergeView(h.present, resolved));
            return justSaved ? { ...merged, saved: justSaved } : merged;
          });
        }
        loaded.current = true;
      })
      .catch((err) => {
        if (mine === request.current) setLoadError(toErrorMessage(err, "This diagram could not be found, or you do not have access to it."));
      });
  }, [api, diagramId]);

  useEffect(() => { void read(false); }, [read]);

  const reloadModel = useCallback(
    () => api.model(diagramId).then(setModel).catch((err) => setSaveError(toErrorMessage(err, "Could not read the diagram's connections."))),
    [api, diagramId],
  );

  /** Runs a store call, and sorts a refusal into a conflict (a newer save exists) or a message. */
  const store = useCallback(async (call: (version: number) => Promise<ArchitectureDiagram>): Promise<boolean> => {
    if (!diagram) return false;
    setSaving(true);
    setSaveError(null);
    try {
      setDiagramState(await call(diagram.version));
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setConflict(true);
      else setSaveError(toErrorMessage(err, "Could not save the diagram."));
      return false;
    } finally {
      setSaving(false);
    }
  }, [diagram]);

  const save = useCallback(async () => {
    const sent = history.present;
    const { placements, notes, anchors } = layoutToSave(sent);
    if (!(await store((version) => api.saveLayout(diagramId, version, placements, notes, anchors)))) return false;
    // The stored layout is the baseline at once: the read-back below may be overtaken by a later read, which must not
    // leave the saved layout looking unsaved.
    setHistory((h) => ({ ...h, saved: sent }));
    await read(sent);
    return true;
  }, [store, read, api, diagramId, history.present]);

  const saveToggles = useCallback(async (values: DiagramToggleValues[]) => {
    if (!(await store((version) => api.saveToggles(diagramId, version, values)))) return false;
    await read(false);
    return true;
  }, [store, read, api, diagramId]);

  const updateFields = useCallback(async (values: Partial<DiagramFieldValues>) => {
    if (!(await store((version) => api.update(diagramId, version, values)))) return false;
    await read(false);
    return true;
  }, [store, read, api, diagramId]);

  return {
    diagram, view, model, layout: history.present, loadError, saveError, conflict, saving,
    dirty: isDirty(history), canUndo: history.past.length > 0, canRedo: history.future.length > 0,
    edit: (change) => setHistory((h) => commit(h, change(h.present))),
    undo: () => setHistory(undo),
    redo: () => setHistory(redo),
    save, saveToggles, updateFields,
    reload: (discard = false) => read(discard),
    reloadModel,
    setDiagram: setDiagramState,
  };
}
