/**
 * Module: components/ReportSnippetEditorDialog
 *
 * The dialog that creates a saved report snippet from nothing, or edits an existing one: its details (name, description,
 * category) and its blocks, in the same Blocks and Text editors a layout is written in.
 *
 * Responsibilities:
 * - Create: choose the kind first (document or table, since a snippet's blocks are checked against a family), then build the
 *   blocks from an empty tree. The kind is fixed once the first block exists.
 * - Edit: load the snippet's blocks (with the page styles and variables it carries) into the same editors.
 * - Switch between Blocks (`ReportLayoutBlocks`, lazy) and Text (parse and format by the server) without keeping a second
 *   model: one tree, with the text view's text only parsed back when it is valid.
 * - Ask the server what saving the blocks would store (`ReportSnippetStoreApi.check`, whole tree selected) as they change and
 *   show it through `ReportSnippetCheckSummary`; save through the existing `save` (new) or `update` (existing) calls.
 *
 * Design decisions: no editing surface of its own: the snippet is a layout fragment, so the layout editors are reused as they
 * are. The server decides every rule, so this dialog and the designer's Save as snippet cannot disagree. The empty tree of a
 * kind is written by the server (`parseText("@layout <kind>")`), never spelled out here. Follows the form header, required-
 * field and field-help patterns.
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api/client";
import {
  LAYOUT_FAMILY_LABEL, treeProblems, type BlockCatalogue, type LayoutFamily, type ReportFieldCatalogue, type ReportLayoutApi, type ReportWidget,
  type TextParseResult, type TreeProblem,
} from "../api/reportLayouts";
import type { ReportSnippetStoreApi, SavedSnippet, SnippetCheck } from "../api/reportSnippets";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useRequestSequence } from "../hooks/useRequestSequence";
import type { Tree } from "../utils/reportLayoutTree";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { FormActions } from "./FormActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { ReportSnippetCheckSummary } from "./ReportSnippetCheckSummary";
import { ReportSnippetFields } from "./ReportSnippetFields";
import { Spinner } from "./Spinner";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";

/** How long editing must pause before the blocks or text are checked. */
export const SNIPPET_CHECK_DELAY_MS = 400;
/** Tallest the text editor grows before it scrolls, in lines. */
const EDITOR_MAX_LINES = 30;

/** Blockly is large, so the block editor is fetched only when the dialog opens. */
const ReportLayoutBlocks = lazy(() => import("./ReportLayoutBlocks").then((m) => ({ default: m.ReportLayoutBlocks })));

type EditorView = "blocks" | "text";

interface Tools {
  catalogue: ReportFieldCatalogue;
  widgets: ReportWidget[];
  blocks: BlockCatalogue;
}

/** The number of top-level blocks of a tree. */
function blockCount(tree: Tree | null): number {
  return tree !== null && Array.isArray(tree.nodes) ? tree.nodes.length : 0;
}

/**
 * @param api The saved-snippet calls, bound to the scope that owns the snippet (or will own the new one).
 * @param layoutApi The layout calls of the same scope: block types, fields, widgets, pictures and the text parser.
 * @param snippet The snippet to edit; omit it to create one.
 * @param categories The categories already in use, offered as suggestions.
 * @param onClose Called by Cancel.
 * @param onSaved Called with the saved snippet; the caller closes the dialog, toasts and reloads.
 */
export function ReportSnippetEditorDialog({
  api, layoutApi, snippet, categories, onClose, onSaved,
}: {
  api: ReportSnippetStoreApi;
  layoutApi: ReportLayoutApi;
  snippet?: SavedSnippet;
  categories: string[];
  onClose: () => void;
  onSaved: (saved: SavedSnippet) => void;
}) {
  const strings = useStrings();
  const text = strings.reportSnippetEditor;
  const saveText = strings.reportSnippetSave;
  const level = api.scope.kind;
  const beginCheck = useRequestSequence();
  const [name, setName] = useState(snippet?.name ?? "");
  const [description, setDescription] = useState(snippet?.description ?? "");
  const [category, setCategory] = useState(snippet?.category ?? "");
  const [family, setFamily] = useState<LayoutFamily>(snippet?.family ?? "document");
  const [tools, setTools] = useState<Tools | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [tree, setTree] = useState<Tree | null>(null);
  const [view, setView] = useState<EditorView>("blocks");
  const [draft, setDraft] = useState("");
  const [parsed, setParsed] = useState<{ text: string; result: TextParseResult | null } | null>(null);
  const [problems, setProblems] = useState<TreeProblem[]>([]);
  const [viewNote, setViewNote] = useState<string | null>(null);
  /** The latest server check and the exact tree it was for, so a check of an earlier edit is never shown. */
  const [checked, setChecked] = useState<{ tree: Tree; result: SnippetCheck } | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checkTicket = useRef(0);

  /** The empty tree of a kind, as the server writes it. */
  const emptyTree = useCallback(async (kind: LayoutFamily): Promise<Tree> => {
    const result = await layoutApi.parseText(`@layout ${kind}\n`);
    if (!result.tree) throw new Error("empty tree");
    return result.tree;
  }, [layoutApi]);

  // Load the editors' catalogues and the tree to start from: the snippet's own blocks, or an empty tree of the chosen kind.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [catalogue, widgets, blocks] = await Promise.all([layoutApi.fields(), layoutApi.widgets(), layoutApi.blocks()]);
        const base = await emptyTree(snippet?.family ?? "document");
        const detail = snippet ? await api.get(snippet.id) : null;
        if (cancelled) return;
        setTools({ catalogue, widgets, blocks });
        setTree(detail ? { ...base, ...detail.root, nodes: detail.nodes } : base);
      } catch {
        if (!cancelled) setLoadFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [api, layoutApi, snippet, emptyTree]);

  // Text view: parse the text once typing pauses.
  useEffect(() => {
    if (view !== "text" || tools === null) return undefined;
    const timer = window.setTimeout(() => {
      const isLatest = beginCheck();
      layoutApi.parseText(draft).then(
        (result) => { if (isLatest()) setParsed({ text: draft, result }); },
        () => { if (isLatest()) setParsed({ text: draft, result: null }); },
      );
    }, SNIPPET_CHECK_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [draft, view, tools, layoutApi, beginCheck]);

  /** The tree a save would store: the block editor's, or the text's when it parsed cleanly; `null` while the text has problems. */
  const current: Tree | null = useMemo(() => {
    if (view === "blocks") return tree;
    return parsed !== null && parsed.text === draft && parsed.result?.ok === true ? (parsed.result.tree ?? null) : null;
  }, [view, tree, parsed, draft]);
  const count = blockCount(current);

  // Blocks view: check the tree for the block editor's warnings once editing pauses.
  useEffect(() => {
    if (view !== "blocks" || tree === null || tools === null) return undefined;
    const timer = window.setTimeout(() => {
      const isLatest = beginCheck();
      layoutApi.validate(tree).then(
        (result) => { if (isLatest()) setProblems(result.errors); },
        () => { if (isLatest()) setProblems([]); },
      );
    }, SNIPPET_CHECK_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [tree, view, tools, layoutApi, beginCheck]);

  // Ask the server what saving these blocks would store (nothing is stored).
  useEffect(() => {
    if (current === null || count === 0) return undefined;
    const ticket = ++checkTicket.current;
    const timer = window.setTimeout(() => {
      api.check(current, { container: "nodes", start: 0, count }, level).then(
        (found) => { if (ticket === checkTicket.current) { setChecked({ tree: current, result: found }); setCheckError(null); } },
        (err) => { if (ticket === checkTicket.current) setCheckError(toErrorMessage(err, saveText.checkFailed)); },
      );
    }, SNIPPET_CHECK_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [api, current, count, level, saveText.checkFailed]);

  async function chooseFamily(next: LayoutFamily) {
    setFamily(next);
    try {
      setTree(await emptyTree(next));
    } catch {
      setLoadFailed(true);
    }
  }

  async function switchView(next: EditorView) {
    if (next === view) return;
    setViewNote(null);
    try {
      if (next === "text") {
        if (tree === null) return;
        setDraft(await layoutApi.formatTree(tree));
        setParsed(null);
        setView("text");
      } else {
        if (parsed === null || parsed.text !== draft || parsed.result?.ok !== true || !parsed.result.tree) {
          setViewNote(text.fixTextFirst);
          return;
        }
        setTree(parsed.result.tree);
        setView("blocks");
      }
    } catch (err) {
      setViewNote(toErrorMessage(err, strings.common.error));
    }
  }

  async function save() {
    if (current === null || count === 0) return;
    setBusy(true);
    setError(null);
    try {
      const details = { name: name.trim(), description: description.trim(), category: category.trim() };
      onSaved(
        snippet
          ? await api.update(snippet.id, { ...details, tree: current })
          : await api.save({ ...details, tree: current, selection: { container: "nodes", start: 0, count } }, level),
      );
    } catch (err) {
      const reasons = treeProblems(err).map((p) => p.message);
      setError(err instanceof ApiError && err.status === 409 ? saveText.nameTaken : reasons.length > 0 ? reasons.join(" ") : toErrorMessage(err, text.saveFailed));
    } finally {
      setBusy(false);
    }
  }

  const tabs: TabDef<EditorView>[] = [{ key: "blocks", label: text.blocksTab }, { key: "text", label: text.textTab }];
  const textProblems = view === "text" && parsed?.text === draft ? (parsed.result?.errors ?? []) : [];
  const check = current !== null && count > 0 && checked?.tree === current ? checked.result : null;
  const canSave = !busy && name.trim() !== "" && count > 0 && check?.ok === true;
  return (
    <Modal title={snippet ? strings.reportSnippetsPanel.editTitle(snippet.name) : text.createTitle} size="lg" onClose={onClose}>
      <div className="stack">
        <FormActions
          error={error} onCancel={onClose} onSave={() => void save()} saveLabel={busy ? saveText.saving : snippet ? strings.common.save : saveText.saveButton}
          saveDisabled={!canSave} cancelDisabled={busy}
        />
        {!snippet && (
          <LabeledSelect
            required label={text.familyLabel} help={strings.help.reportSnippetFamily} value={family} placeholder={null}
            disabled={blockCount(tree) > 0} onChange={(value: string) => void chooseFamily(value as LayoutFamily)}
            options={(Object.keys(LAYOUT_FAMILY_LABEL) as LayoutFamily[]).map((key) => ({ value: key, label: LAYOUT_FAMILY_LABEL[key] }))}
          />
        )}
        <ReportSnippetFields
          name={name} description={description} category={category} categories={categories}
          onName={setName} onDescription={setDescription} onCategory={setCategory}
        />
        {loadFailed ? <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{text.loadFailed}</p> : tools === null || tree === null ? <Spinner /> : (
          <>
            <Tabs<EditorView> idPrefix="snippet-editor-view" tabs={tabs} active={view} onChange={(next) => void switchView(next)} />
            {viewNote && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{viewNote}</p>}
            {view === "blocks" && (
              <div {...tabPanelProps("snippet-editor-view", "blocks")} className="stack">
                <Suspense fallback={<Spinner />}>
                  <ReportLayoutBlocks
                    tree={tree} onChange={setTree} family={snippet?.family ?? family} blocks={tools.blocks} catalogue={tools.catalogue}
                    widgets={tools.widgets} problems={problems} images={{ library: layoutApi.images, scope: layoutApi.scope.kind }}
                  />
                </Suspense>
                {problems.length > 0 && <strong>{strings.reportOutline.outlineProblemsTitle(problems.length)}</strong>}
              </div>
            )}
            {view === "text" && (
              <div {...tabPanelProps("snippet-editor-view", "text")} className="stack">
                <AutoGrowTextarea
                  className="input layout-editor" value={draft} onChange={setDraft} rows={12} maxVisibleLines={EDITOR_MAX_LINES}
                  aria-label={text.textLabel} spellCheck={false}
                />
                {textProblems.length > 0 && (
                  <ul className="layout-problems" aria-label={strings.reportLayouts.problemsTitle(textProblems.length)}>
                    {textProblems.map((problem, index) => (
                      <li key={index} style={{ color: "var(--color-danger)" }}>{strings.reportLayouts.problemLine(problem.line, problem.column)}: {problem.message}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {count === 0 ? <span className="text-muted">{text.needsBlock}</span> : <ReportSnippetCheckSummary check={check} error={checkError} />}
          </>
        )}
      </div>
    </Modal>
  );
}
