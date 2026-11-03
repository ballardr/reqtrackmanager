/**
 * Module: hooks/useLayoutDraft
 *
 * The designer's side of a layout's shared draft (the server keeps one working copy per layout, separate from its
 * numbered versions): what the server holds, when to write the editor's tree into it, and how a publish goes through it.
 *
 * Responsibilities:
 * - Remember the tree the server last confirmed (the draft's, else the saved version's) and its `revision`, so the
 *   editor knows whether it has changes the server does not hold (`pending`).
 * - With `autosave` on, write the tree once editing pauses (`delayMs`); with it off, write only when {@link LayoutDraftSession.saveNow}
 *   is called. Writes run one after another, each with the revision the last one returned, so the editor never conflicts with itself.
 * - Report why nothing was written: the draft moved on under another editor (`conflict`, autosave pauses until
 *   {@link LayoutDraftSession.keepMine} or a fresh {@link LayoutDraftSession.start}), the network or server failed (`failure`, retried
 *   on the next change), or the editor's content cannot be a tree yet (`unreadable`, shown by the status line).
 * - Publish: write what is pending, then publish the draft as the next version with the revision just written. A draft
 *   begun on an older version is refused by the server; {@link LayoutDraftSession.rebase} is the author's explicit choice to keep
 *   their content on the newer version, written with the new base.
 *
 * Design decisions: the hook never reads or checks a tree; the server validates on publish and a draft may be invalid, so an
 * invalid tree is still written. A version conflict (a version published since the draft began) is handed to
 * `onVersionConflict` so the designer keeps one banner for it.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api/client";
import {
  conflictVersion, draftConflict, draftSummary, type ReportLayoutApi, type ReportLayoutDetail, type ReportLayoutDraftSummary,
} from "../api/reportLayouts";
import { stableJson, type Tree } from "../utils/reportLayoutTree";

/** How long editing must pause before the draft is written (a few seconds, so a burst of typing is one write). */
export const DRAFT_AUTOSAVE_DELAY_MS = 3000;

/** Why a write did not reach the server: no answer at all, or an answer that was an error. */
export type DraftFailure = "offline" | "error";

/** Where the draft stands after the draft was moved on by someone else; `draft` is `null` when they published or discarded it. */
export interface DraftMoved {
  draft: ReportLayoutDraftSummary | null;
}

export interface LayoutDraftSession {
  /** Who last wrote the draft the server holds, and when; `null` when there is none. */
  summary: ReportLayoutDraftSummary | null;
  /** The editor holds changes the server does not (unwritten, unreadable or still being checked). */
  pending: boolean;
  /** A write is under way. */
  saving: boolean;
  /** The last write failed (cleared by the next success). */
  failure: DraftFailure | null;
  /** Someone else changed the draft; writing is paused. */
  conflict: DraftMoved | null;
  /** The tree the server last confirmed, as stable JSON (`null` before {@link start}). */
  storedJson: string | null;
  /** Begins from a loaded layout: the tree the editor opens on and the draft behind it, if any. */
  start(from: { tree: Tree; summary: ReportLayoutDraftSummary | null; currentVersion: number }): void;
  /** Writes the editor's tree now; resolves to whether the server holds it afterwards. */
  saveNow(): Promise<boolean>;
  /** Resumes writing over the draft someone else changed. */
  keepMine(): void;
  /** Keeps the editor's content as a draft of `version` (the latest), so it can be published over a version saved since it began. */
  rebase(version: number): void;
  /**
   * Writes what is pending and publishes the draft as the next version. Resolves to the saved layout, to `"unchanged"`
   * when the editor's tree equals the saved version (no draft is kept), or to `null` when it could not be done (a write failed
   * or the draft was changed by someone else, which is then in `conflict`).
   *
   * Raises whatever the server refused with except a moved draft (a version conflict, an invalid tree).
   */
  publish(note: string): Promise<ReportLayoutDetail | "unchanged" | null>;
}

/**
 * @param api The calls, bound to the layout's scope.
 * @param layoutId The layout.
 * @param enabled Whether autosave may run (an editable layout, loaded, with no version conflict showing). An explicit
 *   {@link LayoutDraftSession.saveNow}, {@link LayoutDraftSession.rebase} or {@link LayoutDraftSession.publish} is the person's own choice and never waits for it.
 * @param tree The tree the editor holds, or `null` when its content cannot be read as one.
 * @param unreadable Why the content cannot be stored ("line 7", "invalid JSON"); `null` when it can or when `tree` is set.
 * @param checking The content is still being read (the text view between a keystroke and its check), so what it holds is unknown.
 * @param unchangedFrom The tree (as stable JSON) the editor's untouched content stands for, or `null` when it was edited. Equal to what the
 *   server holds, the editor has nothing to write whatever `tree` reads as (the text view, opened and not typed in, is read back
 *   by the server's parser and may come out normalised).
 * @param autosave Whether to write once editing pauses.
 * @param delayMs The pause, in milliseconds.
 * @param onVersionConflict Called with the layout's current version when a version was published since the draft began.
 */
export function useLayoutDraft({
  api, layoutId, enabled, tree, unreadable, checking, unchangedFrom, autosave, delayMs = DRAFT_AUTOSAVE_DELAY_MS, onVersionConflict,
}: {
  api: ReportLayoutApi;
  layoutId: string;
  enabled: boolean;
  tree: Tree | null;
  unreadable: string | null;
  checking: boolean;
  unchangedFrom: string | null;
  autosave: boolean;
  delayMs?: number;
  onVersionConflict: (currentVersion: number) => void;
}): LayoutDraftSession {
  const [summary, setSummary] = useState<ReportLayoutDraftSummary | null>(null);
  const [storedJson, setStoredJson] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<DraftFailure | null>(null);
  const [conflict, setConflict] = useState<DraftMoved | null>(null);

  const revision = useRef(0);
  const base = useRef(1);
  /** The base version the server holds the draft at (or the current version when there is no draft). */
  const serverBase = useRef(1);
  const currentVersion = useRef(1);
  const stored = useRef<string | null>(null);
  const moved = useRef<DraftMoved | null>(null);
  const treeRef = useRef<Tree | null>(tree);
  const unchanged = unchangedFrom !== null && unchangedFrom === storedJson;
  const unchangedRef = useRef(unchanged);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const treeJson = useMemo(() => (tree === null ? null : stableJson(tree)), [tree]);

  useLayoutEffect(() => {
    treeRef.current = tree;
    unchangedRef.current = unchanged;
  });

  const start = useCallback((from: { tree: Tree; summary: ReportLayoutDraftSummary | null; currentVersion: number }) => {
    const json = stableJson(from.tree);
    stored.current = json;
    revision.current = from.summary?.revision ?? 0;
    base.current = from.summary?.base_version ?? from.currentVersion;
    serverBase.current = base.current;
    currentVersion.current = from.currentVersion;
    moved.current = null;
    setStoredJson(json);
    setSummary(from.summary);
    setFailure(null);
    setConflict(null);
  }, []);

  const writeOnce = useCallback(async (): Promise<boolean> => {
    const current = treeRef.current;
    if (moved.current !== null) return false;
    const rebased = base.current !== serverBase.current;
    if (unchangedRef.current && !rebased) return true;
    if (current === null) return false;
    const json = stableJson(current);
    if (json === stored.current && !rebased) return true;
    setSaving(true);
    try {
      const out = await api.writeDraft(layoutId, { tree: current, base_version: base.current, revision: revision.current });
      const draft = out.draft;
      revision.current = draft?.revision ?? 0;
      base.current = draft?.base_version ?? currentVersion.current;
      serverBase.current = base.current;
      stored.current = json;
      setStoredJson(json);
      setSummary(draft ? draftSummary(draft) : null);
      setFailure(null);
      return true;
    } catch (err) {
      const found = draftConflict(err);
      if (found) {
        moved.current = found;
        setConflict(found);
        setFailure(null);
        return false;
      }
      const newer = conflictVersion(err);
      if (newer !== null) onVersionConflict(newer);
      else setFailure(err instanceof ApiError ? "error" : "offline");
      return false;
    } finally {
      setSaving(false);
    }
  }, [api, layoutId, onVersionConflict]);

  const saveNow = useCallback((): Promise<boolean> => {
    const run = chain.current.then(writeOnce, writeOnce);
    chain.current = run.catch(() => undefined);
    return run;
  }, [writeOnce]);

  useEffect(() => {
    if (!enabled || !autosave || unchanged || conflict !== null || treeJson === null || treeJson === storedJson) return;
    const timer = setTimeout(() => { void saveNow(); }, delayMs);
    return () => clearTimeout(timer);
  }, [enabled, autosave, unchanged, conflict, treeJson, storedJson, delayMs, saveNow]);

  const keepMine = useCallback(() => {
    const found = moved.current;
    if (found === null) return;
    revision.current = found.draft?.revision ?? 0;
    base.current = found.draft?.base_version ?? currentVersion.current;
    serverBase.current = base.current;
    moved.current = null;
    setSummary(found.draft);
    setConflict(null);
    void saveNow();
  }, [saveNow]);

  const rebase = useCallback((version: number) => {
    base.current = version;
    currentVersion.current = version;
    void saveNow();
  }, [saveNow]);

  const publish = useCallback(async (note: string): Promise<ReportLayoutDetail | "unchanged" | null> => {
    if (!(await saveNow())) return null;
    if (revision.current === 0) return "unchanged";
    try {
      return await api.publishDraft(layoutId, { draft_revision: revision.current, comment: note });
    } catch (err) {
      const found = draftConflict(err);
      if (!found) throw err;
      moved.current = found;
      setConflict(found);
      return null;
    }
  }, [api, layoutId, saveNow]);

  const pending = !unchanged && (unreadable !== null || checking || (treeJson !== null && treeJson !== storedJson));

  return { summary, pending, saving, failure, conflict, storedJson, start, saveNow, keepMine, rebase, publish };
}
