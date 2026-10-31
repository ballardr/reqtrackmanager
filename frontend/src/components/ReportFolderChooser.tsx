/**
 * Module: components/ReportFolderChooser
 *
 * The one control for the Reports picker folder a layout, a pack or a placement is filed under: a tree of the folders the
 * scope can use, with New folder, Rename and Delete beside it. It replaces typing a path, so a folder cannot be misspelt
 * and a person sees where other reports live.
 *
 * Responsibilities:
 * - Show the folders (`useReportFolders`, plus any `extraPaths` such as a module report's default folder) as a tree with
 *   a "no folder" row first; choosing a row calls `onChange` with its path.
 * - Add a folder under the chosen one, rename the chosen folder's last level, or delete it behind a confirm (what is filed
 *   in it moves up one level; no report is deleted). The value follows the change, and every change ends in a Toast.
 * - Offer Rename and Delete only for a folder the scope owns, with the reason when it is not.
 *
 * Design decisions: folders are labels, so deleting moves contents rather than deleting reports (see the decisions log's
 * folder chooser entry); the server stays authoritative on depth, length and duplicates and its refusal is shown in the
 * control. The control sits inside a form, so Enter in its name box applies the name instead of submitting the form.
 *
 * Dependencies: `TreeView`, `ConfirmDialog`, `FieldShell`, `api/reportFolders`.
 */
import { FolderPlus, Pencil, Trash2 } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";

import type { ReportFolderApi } from "../api/reportFolders";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useReportFolders } from "../hooks/useReportFolders";
import {
  FOLDER_SEPARATOR, MAX_FOLDER_DEPTH, distinctFolders, folderLevels, folderNodeId, folderProblem, parentFolder, tidyFolder,
} from "../utils/reportFolders";
import { ConfirmDialog } from "./ConfirmDialog";
import { FieldShell } from "./FieldHelp";
import { TextField } from "./FormFields";
import { TreeView, type TreeViewNode } from "./TreeView";

interface ChooserNode extends TreeViewNode<ChooserNode> {
  path: string;
  name: string;
}

/** The nested nodes of `paths` (each path's levels above it are already in the list). */
function buildNodes(paths: string[]): ChooserNode[] {
  const nodes = new Map<string, ChooserNode>();
  const roots: ChooserNode[] = [];
  for (const path of paths) {
    const levels = folderLevels(path);
    const node: ChooserNode = { id: folderNodeId(path, "c"), path, name: levels[levels.length - 1] ?? path, children: [] };
    nodes.set(path.toLowerCase(), node);
    const parent = nodes.get(parentFolder(path).toLowerCase());
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}

type Editor = { mode: "add" | "rename"; name: string } | null;

/**
 * @param value The chosen folder path (`""` = none).
 * @param onChange Called with the path when a row is chosen, and when a rename or delete moves the chosen folder.
 * @param api The folder calls, bound to the organisation or project the report belongs to.
 * @param label Overrides the default caption.
 * @param helpKey Which help text to show (a placement's describes moving a report).
 * @param noneLabel The first row: what an empty folder means here (the picker's default folder, or the top level).
 * @param extraPaths Further folders to offer that the scope does not own (a module report's default folder).
 * @param onChanged Called after a folder is added, renamed or deleted, so the page behind can reload what it lists.
 * @param onBusyChange Told when a folder change starts and ends, so the form can keep Save disabled until the value has followed it.
 * @param onPick Called after a row is chosen (not after a rename, add or delete moves the value), so a host can close itself.
 * @param onConfirmChange Told when the delete confirmation opens and closes, so a popover host stays open behind it.
 */
export function ReportFolderChooser({
  value, onChange, api, label, helpKey = "reportFolder", noneLabel, extraPaths = [], onChanged, onBusyChange, onPick, onConfirmChange,
}: {
  value: string;
  onChange: (path: string) => void;
  api: ReportFolderApi;
  label?: string;
  helpKey?: "reportFolder" | "reportPlacementFolder";
  noneLabel?: string;
  extraPaths?: string[];
  onChanged?: () => void;
  onBusyChange?: (busy: boolean) => void;
  onPick?: (path: string) => void;
  onConfirmChange?: (open: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.reportFolders;
  const { showToast } = useToast();
  const folders = useReportFolders(api);
  const controlId = useId();
  const [editor, setEditor] = useState<Editor>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => onBusyChange?.(busy), [busy, onBusyChange]);
  useEffect(() => onConfirmChange?.(confirmDelete), [confirmDelete, onConfirmChange]);
  const pick = (path: string) => {
    onChange(path);
    onPick?.(path);
  };

  const chosen = tidyFolder(value);
  const owned = useMemo(() => new Set(folders.folders.filter((f) => f.own).map((f) => f.path.toLowerCase())), [folders.folders]);
  const nodes = useMemo(
    () => buildNodes(distinctFolders([...folders.folders.map((f) => f.path), ...extraPaths, chosen])),
    [folders.folders, extraPaths, chosen],
  );
  const canChange = chosen !== "" && owned.has(chosen.toLowerCase());
  const canAdd = !folders.failed && folderLevels(chosen).length < MAX_FOLDER_DEPTH;

  function open(mode: "add" | "rename") {
    setError(null);
    setEditor({ mode, name: mode === "rename" ? folderLevels(chosen).slice(-1)[0] ?? "" : "" });
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  const apply = () => editor && run(async () => {
    const name = editor.name.trim();
    if (editor.mode === "add") {
      const path = tidyFolder(chosen === "" ? name : `${chosen}${FOLDER_SEPARATOR}${name}`);
      const problem = folderProblem(path);
      if (problem) throw new Error(problem);
      await folders.add(path);
      onChange(path);
      showToast(text.added(path));
    } else {
      const change = await folders.rename(chosen, name);
      onChange(change.path ?? chosen);
      showToast(text.renamed(change.path ?? name, change.layouts + change.packs + change.placements));
    }
    setEditor(null);
    onChanged?.();
  });

  const remove = () => run(async () => {
    const change = await folders.remove(chosen);
    onChange(parentFolder(chosen));
    showToast(text.deleted(chosen, change.layouts + change.packs + change.placements));
    setConfirmDelete(false);
    onChanged?.();
  });

  const reason = chosen === "" ? text.pickToChange : text.notOwned;
  return (
    <>
      <FieldShell label={label ?? text.folderLabel} controlId={controlId} help={strings.help[helpKey]}>
        <div
          id={controlId} role="radiogroup" aria-label={label ?? text.folderLabel}
          style={{ border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", padding: "var(--space-2)", maxHeight: "14rem", overflowY: "auto" }}
        >
          <ChoiceRow label={noneLabel ?? text.none} selected={chosen === ""} onSelect={() => pick("")} />
          <TreeView
            nodes={nodes} nodeLabel={(node) => node.name} emptyText={text.empty}
            renderNode={(node) => <ChoiceRow label={node.name} selected={isSameFolder(node.path, chosen)} onSelect={() => pick(node.path)} />}
          />
        </div>
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>{chosen === "" ? (noneLabel ?? text.none) : chosen}</span>
        <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
          <button type="button" className="btn btn-sm" disabled={!canAdd || busy} onClick={() => open("add")}
            title={canAdd ? undefined : text.tooDeep}>
            <FolderPlus size={14} aria-hidden /> {chosen === "" ? text.newFolder : text.newInside}
          </button>
          <button type="button" className="btn btn-sm" disabled={!canChange || busy} onClick={() => open("rename")}
            title={canChange ? undefined : reason}>
            <Pencil size={14} aria-hidden /> {text.rename}
          </button>
          <button type="button" className="btn btn-sm" disabled={!canChange || busy} onClick={() => { setError(null); setConfirmDelete(true); }}
            title={canChange ? undefined : reason}>
            <Trash2 size={14} aria-hidden /> {text.delete}
          </button>
        </div>
        {editor && (
          <div className="row" style={{ gap: "var(--space-2)", alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <TextField helpNotNeeded
                label={editor.mode === "add" ? text.nameLabel(chosen) : text.renameLabel(chosen)} value={editor.name}
                onChange={(name) => setEditor({ ...editor, name })}
                inputProps={{
                  maxLength: 40, autoFocus: true,
                  onKeyDown: (e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      if (editor.name.trim() !== "") void apply();
                    } else if (e.key === "Escape") {
                      e.stopPropagation();
                      setEditor(null);
                    }
                  },
                }}
              />
            </div>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy || editor.name.trim() === ""} onClick={() => void apply()}>
              {editor.mode === "add" ? text.add : text.renameApply}
            </button>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditor(null)}>{strings.common.cancel}</button>
          </div>
        )}
        {error && <span role="alert" className="text-danger" style={{ fontSize: "0.85rem" }}>{error}</span>}
        {folders.failed && <span className="text-muted" style={{ fontSize: "0.8rem" }}>{text.loadFailed}</span>}
      </FieldShell>
      {confirmDelete && (
        <ConfirmDialog
          title={text.deleteTitle(chosen)} message={text.deleteMessage(parentFolder(chosen))} confirmLabel={text.delete}
          confirmDisabled={busy} onConfirm={() => void remove()} onCancel={() => setConfirmDelete(false)}
        />
      )}
    </>
  );
}

/** Whether two folder paths are the same folder (case-insensitive). */
function isSameFolder(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase();
}

/** One selectable row of the chooser: a radio, so it is named, focusable and announced as chosen or not. */
function ChoiceRow({ label, selected, onSelect }: { label: string; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button" role="radio" aria-checked={selected} className={selected ? "btn btn-primary btn-sm" : "btn btn-sm"}
      style={{ textAlign: "left" }} onClick={onSelect}
    >
      {label}
    </button>
  );
}
