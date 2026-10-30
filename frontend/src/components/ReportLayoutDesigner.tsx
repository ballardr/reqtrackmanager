/**
 * Module: components/ReportLayoutDesigner
 *
 * The report layout designer: where a person writes a layout as text, sees its problems and a live preview, and
 * saves it as a new version. One component for an organisation's and a project's layouts over `ReportLayoutApi`.
 *
 * Responsibilities:
 * - Load a layout and show its current tree as the text view (`ReportLayoutApi.formatTree`), editable in a
 *   monospace box with block shortcuts; a layout shared from elsewhere opens read-only with a "make a copy" route.
 * - Edit the same tree in two views, switchable at any time: the text view and the block editor
 *   (`ReportLayoutBlocks`). The block editor edits one copy of the tree, which it checks with the server's `validate` a
 *   moment after each change and uses to keep the text view's text up to date, so the preview, Save and the switch
 *   back to text all read one layout. A switch from text that has problems is refused, with the reason.
 * - Check the text a moment after typing stops (`parseText`) and list every problem by line, each jumping to its
 *   line; Save is available only for text that parsed cleanly, and sends the parsed tree with the version the
 *   author started from, so a concurrent save is reported (409) instead of overwritten.
 * - Offer, beside the text editor, the live preview, the field picker and the widget picker, which insert at the
 *   caret; and, on a second tab, the version history and comparison. The block editor takes the full width: its
 *   preview opens in a dialog (Preview) or, when the person turns it on, as a panel beside the blocks (remembered).
 * - Insert a snippet (`ReportSnippetPicker`) from either view and report what the server did (`ReportSnippetNotice`). In
 *   the Blocks view the editor places the blocks itself (Ctrl+Z undoes them); in the Text view the draft is read as a
 *   layout, the server inserts the snippet at the start or end of it and the text is written again from the result,
 *   with an Undo while that text stands.
 * - Save a selection as a snippet (`ReportSaveSnippetDialog`): the selected block of the Blocks view, or the top-level blocks
 *   the Text view's selection or caret touches (the server's parse says which line each block starts on).
 * - Warn before leaving with unsaved changes (the Back link and the browser's own unload prompt).
 *
 * Design decisions: the text view is the only editing surface here and the server the only parser, so the client
 * holds no block model that could drift from the tree (the WYSIWYG editor later edits the same tree). The saved
 * text is the author's own, not re-formatted, so Save never reflows what they typed. Pickers only insert text.
 */
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  conflictVersion, LAYOUT_FAMILY_LABEL, LAYOUT_ORIGIN_LABEL, reportLayoutPath, treeProblems,
  type BlockCatalogue, type ReportFieldCatalogue, type ReportLayoutApi, type ReportLayoutDetail, type ReportSnippet, type ReportWidget,
  type SnippetApplyResult, type TextParseResult, type TreeCheck,
} from "../api/reportLayouts";
import { reportDuplicateApi, type DuplicateResult, type ReportDuplicateApi } from "../api/reportDuplicate";
import { reportSnippetStoreApi, type ReportSnippetStoreApi, type SnippetSelection } from "../api/reportSnippets";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { useUiPreference } from "../hooks/useUiPreference";
import {
  aliasesInScope, asBlock, insertAt, insertionRange, lineOfOffset, offsetOfLine,
} from "../utils/reportLayoutText";
import { stableJson, type Tree } from "../utils/reportLayoutTree";
import { selectionFromLines } from "../utils/reportSnippetSelection";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { Modal } from "./Modal";
import { ReportDuplicateDialog } from "./ReportDuplicateDialog";
import { ReportLayoutBlockToolbar } from "./ReportLayoutBlockToolbar";
import { ReportLayoutFieldPicker } from "./ReportLayoutFieldPicker";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";
import { ReportLayoutHistory } from "./ReportLayoutHistory";
import { ReportLayoutPageSetup } from "./ReportLayoutPageSetup";
import { ReportLayoutPreviewPanel } from "./ReportLayoutPreviewPanel";
import { ReportLayoutWidgetPicker } from "./ReportLayoutWidgetPicker";
import { ReportSaveSnippetDialog } from "./ReportSaveSnippetDialog";
import { ReportSnippetNotice, type SnippetNoticeData } from "./ReportSnippetNotice";
import { ReportSnippetPicker } from "./ReportSnippetPicker";
import { RecordHeader } from "./RecordHeader";
import { SaveVersionButton } from "./SaveVersionButton";
import { Spinner } from "./Spinner";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";

/** How long typing must pause before the text is checked. */
export const TEXT_CHECK_DELAY_MS = 400;
/** Tallest the editor grows before it scrolls, in lines. */
const EDITOR_MAX_LINES = 40;

type MainTab = "design" | "history";
/** Blockly is large, so the block editor is fetched only when the author opens the Blocks view. */
const ReportLayoutBlocks = lazy(() => import("./ReportLayoutBlocks").then((m) => ({ default: m.ReportLayoutBlocks })));

type EditView = "text" | "blocks";
/** The views that edit the tree itself (the text view edits text). */
const isTreeView = (view: EditView) => view !== "text";
type AsideTab = "preview" | "fields" | "widgets";
type Dialog = "details" | "delete" | "reload" | "leave" | "preview" | "duplicate" | "snippet" | "save-snippet";

/** The last snippet insertion, for the notice above the views; `afterText` is the text view's text it produced (Undo is offered while it still stands). */
interface SnippetNotice extends SnippetNoticeData {
  view: EditView;
  beforeText?: string;
  afterText?: string;
}

/** What Save as snippet was asked to save: the draft tree, the blocks chosen and the words naming them. */
interface SnippetToSave {
  tree: Tree;
  selection: SnippetSelection;
  label: string;
}

/** The outcome of checking one exact block-editor tree. */
interface TreeChecked {
  tree: Tree;
  /** `null` when the check itself could not run. */
  result: TreeCheck | null;
}

/** The outcome of checking one exact text. */
interface Checked {
  text: string;
  /** `null` when the check itself could not run. */
  result: TextParseResult | null;
}

/**
 * @param api The calls, bound to the layout's scope.
 * @param layoutId The layout to open.
 * @param backTo Where the Back link and a delete lead (the list the layout came from).
 * @param projectOptions Organisation scope: the projects a preview can be narrowed to.
 */
export function ReportLayoutDesigner({
  api, layoutId, backTo, projectOptions, duplicateApi: duplicateApiProp, snippetApi: snippetApiProp,
}: {
  api: ReportLayoutApi;
  layoutId: string;
  backTo: string;
  projectOptions?: { value: string; label: string }[];
  /** The calls that duplicate this layout; the live ones for the layout's scope when omitted. */
  duplicateApi?: ReportDuplicateApi;
  /** The calls that save a snippet; the live ones for the layout's scope when omitted. */
  snippetApi?: ReportSnippetStoreApi;
}) {
  const strings = useStrings();
  const text = strings.reportLayouts;
  const outline = strings.reportOutline;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const duplicateApi = useMemo(() => duplicateApiProp ?? reportDuplicateApi(api.scope), [duplicateApiProp, api.scope]);
  const snippetStore = useMemo(() => snippetApiProp ?? reportSnippetStoreApi(api.scope), [snippetApiProp, api.scope]);
  const beginCheck = useRequestSequence();

  const [detail, setDetail] = useState<ReportLayoutDetail | null>(null);
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const [draft, setDraft] = useState("");
  const [checked, setChecked] = useState<Checked | null>(null);
  const [catalogue, setCatalogue] = useState<ReportFieldCatalogue | null>(null);
  const [widgets, setWidgets] = useState<ReportWidget[] | null>(null);
  const [blockTypes, setBlockTypes] = useState<BlockCatalogue | null>(null);
  const [view, setView] = useState<EditView>("text");
  /** The tree the block editor edits, and the tree it started from (so a switch back leaves unedited text alone). */
  const [blockTree, setBlockTree] = useState<Tree | null>(null);
  const [enteredTree, setEnteredTree] = useState<Tree | null>(null);
  const [treeChecked, setTreeChecked] = useState<TreeChecked | null>(null);
  /** The tree whose text view is in `draft`: the preview runs on the text, so it waits until the text is for the tree on screen. */
  const [textFor, setTextFor] = useState<Tree | null>(null);
  const [viewNote, setViewNote] = useState<string | null>(null);
  const [toolsFailed, setToolsFailed] = useState(false);
  const [tab, setTab] = useState<MainTab>("design");
  const [aside, setAside] = useState<AsideTab>("preview");
  const [saving, setSaving] = useState(false);
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<number | null>(null);
  const [caretLine, setCaretLine] = useState(0);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  /** The tree the Text view's snippet dialog applies to (the draft as read when the dialog opened), and the last insertion's notice. */
  const [snippetTree, setSnippetTree] = useState<Tree | null>(null);
  const [snippetNotice, setSnippetNotice] = useState<SnippetNotice | null>(null);
  /** The selection the Save as snippet dialog saves. */
  const [toSave, setToSave] = useState<SnippetToSave | null>(null);
  /** Whether the block editor shows the preview as a panel beside the blocks (otherwise only in the Preview dialog). */
  const [previewBeside, setPreviewBeside] = useUiPreference<boolean>("report_layout_preview_beside", false);
  const editor = useRef<HTMLTextAreaElement>(null);
  const pendingCaret = useRef<number | null>(null);
  /** Whether the author has put the caret in the text; until then insertions go to the end, not the untouched start. */
  const caretPlaced = useRef(false);

  const load = useCallback(async () => {
    try {
      const loaded = await api.get(layoutId);
      const written = await api.formatTree(loaded.current.tree);
      setDetail(loaded);
      setSaved(written);
      setDraft(written);
      setView("text");
      setBlockTree(null);
      setEnteredTree(null);
      setViewNote(null);
      setChecked(null);
      setConflict(null);
      setSaveProblems([]);
      setLoadFailed(null);
    } catch (err) {
      setLoadFailed(toErrorMessage(err, strings.common.error));
    }
  }, [api, layoutId, strings.common.error]);

  const loadTools = useCallback(async () => {
    try {
      const [fields, parts, blocks] = await Promise.all([api.fields(), api.widgets(), api.blocks()]);
      setCatalogue(fields);
      setWidgets(parts);
      setBlockTypes(blocks);
      setToolsFailed(false);
    } catch {
      setToolsFailed(true);
    }
  }, [api]);

  useLoadOnChange(load, [api.scope.kind, api.scope.id, layoutId]);
  useLoadOnChange(loadTools, [api.scope.kind, api.scope.id]);

  const loaded = detail !== null;

  // Check the text once typing pauses; a response for text that has since changed is dropped.
  useEffect(() => {
    if (!loaded) return;
    const timer = setTimeout(() => {
      const isLatest = beginCheck();
      api.parseText(draft).then(
        (result) => { if (isLatest()) setChecked({ text: draft, result }); },
        () => { if (isLatest()) setChecked({ text: draft, result: null }); },
      );
    }, TEXT_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [draft, loaded, api, beginCheck]);

  // In the block editor: check the tree once editing pauses, and keep the text view's text in step with it.
  useEffect(() => {
    if (!loaded || !isTreeView(view) || blockTree === null) return;
    const tree = blockTree;
    const timer = setTimeout(() => {
      const isLatest = beginCheck();
      api.validate(tree).then(
        async (result) => {
          if (!isLatest()) return;
          setTreeChecked({ tree, result });
          if (result.ok) {
            const written = await api.formatTree(tree);
            if (isLatest()) {
              setDraft(written);
              setTextFor(tree);
            }
          }
        },
        () => { if (isLatest()) setTreeChecked({ tree, result: null }); },
      );
    }, TEXT_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [blockTree, view, loaded, api, beginCheck]);

  // Put the caret where an insertion left it, once the new text is in the box.
  useLayoutEffect(() => {
    const at = pendingCaret.current;
    const el = editor.current;
    if (at === null || !el) return;
    pendingCaret.current = null;
    el.focus();
    el.setSelectionRange(at, at);
  }, [draft]);

  const blocksChanged = isTreeView(view) && blockTree !== null && detail !== null && stableJson(blockTree) !== stableJson(detail.current.tree);
  const dirty = loaded && (isTreeView(view) ? blocksChanged : draft !== saved);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (loadFailed && !detail) return <p className="text-muted" role="alert">{loadFailed}</p>;
  if (!detail) return <Spinner />;

  const editable = detail.editable;
  const current = checked?.text === draft ? checked : null;
  const wrongKind = current?.result?.tree != null && current.result.tree.family !== detail.family;
  const problems = [
    ...(current?.result && !current.result.ok ? current.result.errors : []),
    // The server parses text without knowing the layout, so a first line naming the other kind is caught here.
    ...(wrongKind ? [{ line: 1, column: null, message: text.familyMismatch(LAYOUT_FAMILY_LABEL[detail.family].toLowerCase()) }] : []),
  ];
  const blockCurrent = treeChecked !== null && treeChecked.tree === blockTree ? treeChecked : null;
  const blockProblems = blockCurrent?.result?.errors ?? [];
  const valid = isTreeView(view)
    ? blockCurrent?.result?.ok === true
    : current?.result?.ok === true && current.result.tree !== null && !wrongKind;
  const aliases = aliasesInScope(draft, caretLine);
  const originLabel = LAYOUT_ORIGIN_LABEL[detail.origin];

  /** Inserts `snippet` over the selection, on its own lines when `block`, and leaves the caret after it. */
  function insert(snippet: string, block: boolean) {
    const el = editor.current;
    const placed = caretPlaced.current && el !== null;
    const range = insertionRange(draft, placed ? el.selectionStart : draft.length, placed ? el.selectionEnd : draft.length);
    const piece = block ? asBlock(draft, range.start, snippet) : snippet;
    const next = insertAt(draft, range.start, range.end, piece);
    pendingCaret.current = next.caret;
    setDraft(next.text);
    setCaretLine(lineOfOffset(next.text, next.caret));
  }

  /** Opens the snippet dialog from the Text view: the draft is read as a layout first, and must read cleanly. */
  async function openTextSnippets() {
    setViewNote(null);
    let parsed: TextParseResult | null = current?.result ?? null;
    if (parsed === null) {
      try {
        parsed = await api.parseText(draft);
      } catch {
        parsed = null;
      }
    }
    const tree = parsed?.ok === true ? parsed.tree : null;
    if (!tree || tree.family !== detail?.family) {
      setViewNote(strings.reportSnippets.textNeedsFixes);
      return;
    }
    setSnippetTree(tree);
    setDialog("snippet");
  }

  /**
   * Opens Save as snippet from the Text view for the top-level blocks the selection (or the caret's line) touches. The draft is
   * read as a layout first, and must read cleanly; the server's parse says which line each block starts on.
   */
  async function openTextSave() {
    const el = editor.current;
    setViewNote(null);
    let parsed: TextParseResult | null = current?.result ?? null;
    if (parsed === null || parsed.block_lines === undefined) {
      try {
        parsed = await api.parseText(draft);
      } catch {
        parsed = null;
      }
    }
    const tree = parsed?.ok === true ? parsed.tree : null;
    if (!tree || tree.family !== detail?.family) {
      setViewNote(strings.reportSnippets.textSaveNeedsFixes);
      return;
    }
    const start = el ? el.selectionStart : 0;
    const end = el ? el.selectionEnd : 0;
    const first = lineOfOffset(draft, start) + 1;
    // A selection that ends at the start of a line does not touch that line.
    const last = Math.max(first, lineOfOffset(draft, end > start && draft[end - 1] === "\n" ? end - 1 : end) + 1);
    const selection = selectionFromLines(parsed?.block_lines ?? {}, first, last);
    if (selection === null) {
      setViewNote(strings.reportSnippets.textSaveNoBlock);
      return;
    }
    setToSave({
      tree, selection,
      label: strings.reportSnippets.saveSelectedMany(selection.count),
    });
    setDialog("save-snippet");
  }

  /** Writes the tree a snippet produced back as the Text view's text, remembering the text it replaced for Undo. */
  async function insertedIntoText(result: SnippetApplyResult, snippet: ReportSnippet) {
    setDialog(null);
    if (result.tree === null) return;
    try {
      const written = await api.formatTree(result.tree);
      setSnippetNotice({
        name: snippet.name, changes: result.changes, problemsElsewhere: result.problems_elsewhere, view: "text", beforeText: draft, afterText: written,
      });
      setDraft(written);
      setChecked(null);
    } catch {
      showToast(strings.reportOutline.outlineFormatFailed, "error");
    }
  }

  function jumpTo(line: number) {
    const el = editor.current;
    if (!el) return;
    const at = offsetOfLine(draft, line);
    el.focus();
    el.setSelectionRange(at, at);
    setCaretLine(line - 1);
  }

  /**
   * Changes the editing view. A switch from the text needs text that reads cleanly; back to the text needs a valid
   * tree; the document needs a tree it can show without changing it. A refusal says why and stays where it is.
   */
  async function switchView(next: EditView) {
    if (next === view) return;
    setViewNote(null);
    setSnippetNotice(null);
    if (next === "text") {
      if (blockTree !== null && enteredTree !== null && stableJson(blockTree) !== stableJson(enteredTree)) {
        try {
          setDraft(await api.formatTree(blockTree));
        } catch {
          setViewNote(strings.reportOutline.outlineFormatFailed);
          return;
        }
      }
      setChecked(null);
      setView("text");
      return;
    }
    let tree = blockTree;
    if (view === "text") {
      // Read the text as it stands now rather than waiting for the pause-and-check, so the switch never refuses a clean text.
      let parsed: TextParseResult | null = current?.result ?? null;
      if (parsed === null) {
        try {
          parsed = await api.parseText(draft);
        } catch {
          parsed = null;
        }
      }
      tree = parsed?.ok === true ? parsed.tree : null;
      if (!tree || tree.family !== detail?.family) {
        setViewNote(strings.reportOutline.outlineNeedsFixes);
        return;
      }
    }
    if (view === "text") {
      setBlockTree(tree);
      setEnteredTree(tree);
      setTextFor(tree);
      setTreeChecked(null);
    }
    setView(next);
  }

  /** Saves the tree on screen as a new version with `note`; resolves to whether a version was stored. */
  async function save(note: string): Promise<boolean> {
    const tree = isTreeView(view) ? blockCurrent?.tree : current?.result?.tree;
    if (!tree || !detail) return false;
    setSaving(true);
    setSaveProblems([]);
    try {
      const result = await api.save(layoutId, { tree, base_version: detail.current_version, comment: note });
      showToast(result.current_version === detail.current_version ? text.noChanges : text.saved(result.current_version));
      setDetail(result);
      const written = isTreeView(view) ? await api.formatTree(tree) : draft;
      setSaved(written);
      if (isTreeView(view)) {
        setDraft(written);
        setEnteredTree(tree);
        setTextFor(tree);
      }
      return true;
    } catch (err) {
      const newer = conflictVersion(err);
      const found = treeProblems(err);
      if (newer !== null) setConflict(newer);
      else if (found.length > 0) setSaveProblems(found.map((p) => text.treeProblem(p.path, p.message)));
      else showToast(toErrorMessage(err, text.saveFailed), "error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  function leave() {
    if (dirty) setDialog("leave");
    else navigate(backTo);
  }

  /** Opens the copy the server made, in its designer at the tier it landed in. */
  function openDuplicate(done: DuplicateResult) {
    setDialog(null);
    if (!done.new_id) return;
    const landed = done.target === "organization" && api.scope.kind === "project" ? { kind: "organization" as const, id: done.organization_id } : api.scope;
    navigate(reportLayoutPath(landed, done.new_id));
  }

  const asideTabs: TabDef<AsideTab>[] = [
    { key: "preview", label: text.previewTab },
    ...(editable && view === "text" ? [{ key: "fields" as const, label: text.fieldsTab }, { key: "widgets" as const, label: text.widgetsTab }] : []),
  ];
  const textTools = editable && view === "text";
  const treeEditing = isTreeView(view);
  const showAside = !treeEditing || previewBeside;
  const preview = (
    <ReportLayoutPreviewPanel
      api={api} text={draft} name={detail.name} disabled={!valid || (treeEditing && textFor !== blockTree)} projectOptions={projectOptions}
    />
  );
  const previewControls = (
    <>
      <button type="button" className="btn" onClick={() => setDialog("preview")}>{text.previewButton}</button>
      <button type="button" className="btn" aria-pressed={previewBeside} onClick={() => setPreviewBeside(!previewBeside)}>
        {text.previewPanelToggle}
      </button>
    </>
  );

  return (
    <div className="stack">
      <RecordHeader
        recordLabel={text.recordLabel}
        title={detail.name}
        subtitle={detail.description || undefined}
        badges={
          <>
            <Badge>{LAYOUT_FAMILY_LABEL[detail.family]}</Badge>
            {detail.origin !== "project" && api.scope.kind === "project" && <Badge>{originLabel}</Badge>}
            {dirty && <Badge tone="warning">{text.unsaved}</Badge>}
          </>
        }
        version={detail.current_version}
        back={{ onClick: leave, label: text.backToList }}
        onEdit={editable ? () => setDialog("details") : undefined}
        actions={[
          { key: "copy", label: text.makeCopy, onSelect: () => setDialog("duplicate") },
          editable && { key: "delete", label: text.delete, danger: true, onSelect: () => setDialog("delete") },
        ]}
      />

      <Tabs
        idPrefix="layout-designer"
        tabs={[{ key: "design", label: text.designTab }, { key: "history", label: text.historyTab }]}
        active={tab}
        onChange={setTab}
      />

      {tab === "history" && (
        <div {...tabPanelProps("layout-designer", "history")}>
          <ReportLayoutHistory
            api={api}
            layoutId={layoutId}
            currentVersion={detail.current_version}
            onUseVersion={editable ? (version, versionText) => {
              setDraft(versionText);
              setView("text");
              setTab("design");
              showToast(text.restoredIntoEditor(version));
            } : undefined}
          />
        </div>
      )}

      {tab === "design" && (
        <div
          {...tabPanelProps("layout-designer", "design")}
          className={`layout-designer${treeEditing ? (previewBeside ? " layout-designer--blocks-preview" : " layout-designer--blocks") : ""}`}
        >
          <div className="stack">
            {!editable && (
              <div className="card" role="note">
                <span className="text-muted">{text.readOnlyNotice(originLabel.toLowerCase())}</span>
              </div>
            )}
            {conflict !== null && (
              <div className="card stack" role="alert">
                <span style={{ color: "var(--color-danger)" }}>{text.conflict(conflict)}</span>
                <div><button type="button" className="btn" onClick={() => setDialog("reload")}>{text.reload}</button></div>
              </div>
            )}
            <Tabs<EditView>
              idPrefix="layout-view"
              tabs={[{ key: "text", label: outline.textView }, { key: "blocks", label: outline.outlineView }]}
              active={view} onChange={(next) => void switchView(next)}
            />
            {viewNote && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{viewNote}</p>}
            {snippetNotice && snippetNotice.view === view && (
              <ReportSnippetNotice
                notice={snippetNotice} onDismiss={() => setSnippetNotice(null)}
                hint={view === "text" ? undefined : strings.reportSnippets.undoBlocksHint}
                onUndo={view === "text" && snippetNotice.afterText === draft && snippetNotice.beforeText !== undefined
                  ? () => { setDraft(snippetNotice.beforeText ?? ""); setChecked(null); setSnippetNotice(null); }
                  : undefined}
              />
            )}
            {view === "text" && (
              <div {...tabPanelProps("layout-view", "text")} className="stack">
              {editable && (
                <div className="row" style={{ alignItems: "center", gap: "var(--space-3)" }}>
                  <ReportLayoutBlockToolbar family={detail.family} onInsert={(snippet) => insert(snippet, true)} />
                  {blockTypes && (
                    <button type="button" className="btn" aria-haspopup="dialog" onClick={() => void openTextSnippets()}>
                      {strings.reportSnippets.insertButton}
                    </button>
                  )}
                  {blockTypes && (
                    <button type="button" className="btn" aria-haspopup="dialog" onClick={() => void openTextSave()}>
                      {strings.reportSnippets.saveFromText}
                    </button>
                  )}
                  <ReportLayoutPageSetup
                    text={draft} onChange={setDraft} images={{ library: api.images, scope: api.scope.kind }}
                    placeholders={catalogue?.placeholders}
                  />
                </div>
              )}
              <AutoGrowTextarea
                textareaRef={editor}
                className="input layout-editor"
                value={draft}
                onChange={setDraft}
                rows={16}
                maxVisibleLines={EDITOR_MAX_LINES}
                aria-label={text.editorLabel}
                spellCheck={false}
                readOnly={!editable}
                onSelect={(e) => {
                  caretPlaced.current = true;
                  setCaretLine(lineOfOffset(draft, e.currentTarget.selectionStart));
                }}
              />
              <div aria-live="polite">
                {current === null && <span className="text-muted">{text.checking}</span>}
                {current && current.result === null && <span role="alert" style={{ color: "var(--color-danger)" }}>{strings.common.error}</span>}
                {valid && <span className="text-muted">{text.noProblems}</span>}
                {problems.length > 0 && (
                  <div className="stack" style={{ gap: "var(--space-2)" }}>
                    <strong>{text.problemsTitle(problems.length)}</strong>
                    <ul className="layout-problems" aria-label={text.problemsTitle(problems.length)}>
                      {problems.map((problem, index) => (
                        <li key={index}>
                          <button type="button" onClick={() => jumpTo(problem.line)}>
                            {text.problemLine(problem.line, problem.column)}: {problem.message}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {saveProblems.length > 0 && (
                  <ul className="layout-problems" role="alert">
                    {saveProblems.map((problem, index) => <li key={index} style={{ color: "var(--color-danger)" }}>{problem}</li>)}
                  </ul>
                )}
              </div>
              </div>
            )}
            {isTreeView(view) && (
              <div {...tabPanelProps("layout-view", view)} className="stack">
                {blockTree && blockTypes && catalogue && widgets ? (
                  <>
                    <Suspense fallback={<Spinner />}>
                      <ReportLayoutBlocks
                        tree={blockTree} onChange={setBlockTree} family={detail.family} blocks={blockTypes} catalogue={catalogue}
                        widgets={widgets} problems={blockProblems} readOnly={!editable} toolbarEnd={previewControls}
                        images={{ library: api.images, scope: api.scope.kind }}
                        snippets={{
                          api,
                          onInserted: (notice) => setSnippetNotice({ ...notice, view }),
                          onSave: (selection, label) => {
                            setToSave({ tree: blockTree, selection, label });
                            setDialog("save-snippet");
                          },
                        }}
                      />
                    </Suspense>
                    <div aria-live="polite">
                      {blockCurrent === null && <span className="text-muted">{outline.outlineChecking}</span>}
                      {blockCurrent && blockCurrent.result === null && <span role="alert" style={{ color: "var(--color-danger)" }}>{strings.common.error}</span>}
                      {blockCurrent?.result?.ok === true && <span className="text-muted">{outline.outlineNoProblems}</span>}
                      {blockProblems.length > 0 && <strong>{outline.outlineProblemsTitle(blockProblems.length)}</strong>}
                    </div>
                    {saveProblems.length > 0 && (
                      <ul className="layout-problems" role="alert">
                        {saveProblems.map((problem, index) => <li key={index} style={{ color: "var(--color-danger)" }}>{problem}</li>)}
                      </ul>
                    )}
                  </>
                ) : toolsFailed ? <p className="text-muted" role="alert">{outline.outlineLoadFailed}</p> : <Spinner />}
              </div>
            )}
            {editable && (
              <div className="row">
                <SaveVersionButton disabled={!valid || !dirty} saving={saving} onSave={save} />
              </div>
            )}
          </div>

          {showAside && (
          <div className="stack" aria-label={text.asideLabel} role="region">
            <Tabs<AsideTab> idPrefix="layout-designer-tools" tabs={asideTabs} active={textTools ? aside : "preview"} onChange={setAside} />
            <div {...tabPanelProps("layout-designer-tools", "preview")} hidden={textTools && aside !== "preview"}>
              {preview}
            </div>
            {textTools && toolsFailed && aside !== "preview" && <p className="text-muted" role="alert">{text.loadToolsFailed}</p>}
            {textTools && (
              <div {...tabPanelProps("layout-designer-tools", "fields")} hidden={aside !== "fields"}>
                {catalogue ? (
                  <ReportLayoutFieldPicker catalogue={catalogue} aliases={aliases} onInsert={(snippet) => insert(snippet, false)} />
                ) : !toolsFailed && <Spinner />}
              </div>
            )}
            {textTools && (
              <div {...tabPanelProps("layout-designer-tools", "widgets")} hidden={aside !== "widgets"}>
                {widgets ? (
                  <ReportLayoutWidgetPicker widgets={widgets} onInsert={(line) => insert(line, true)} />
                ) : !toolsFailed && <Spinner />}
              </div>
            )}
          </div>
          )}
        </div>
      )}

      {dialog === "snippet" && snippetTree && blockTypes && (
        <ReportSnippetPicker
          api={api} family={detail.family} blockTypes={blockTypes.blocks} tree={snippetTree}
          images={{ library: api.images, scope: api.scope.kind }}
          places={[
            { container: "nodes", index: null, label: strings.reportSnippets.atEnd },
            { container: "nodes", index: 0, label: strings.reportSnippets.atStart },
          ]}
          onClose={() => setDialog(null)} onInserted={(result, snippet) => void insertedIntoText(result, snippet)}
        />
      )}
      {dialog === "save-snippet" && toSave && (
        <ReportSaveSnippetDialog
          api={snippetStore} tree={toSave.tree} selection={toSave.selection} selectionLabel={toSave.label}
          onClose={() => setDialog(null)} onSaved={() => setDialog(null)}
        />
      )}
      {dialog === "preview" && (
        <Modal title={text.previewDialogTitle} size="lg" onClose={() => setDialog(null)}>{preview}</Modal>
      )}
      {dialog === "details" && (
        <ReportLayoutFormModal
          api={api}
          layout={detail}
          onClose={() => setDialog(null)}
          onSaved={(updated) => {
            showToast(text.detailsSaved);
            setDetail({
              ...detail, name: updated.name, description: updated.description, folder: updated.folder,
              report_template_id: updated.report_template_id, updated_at: updated.updated_at,
            });
          }}
        />
      )}
      {dialog === "delete" && (
        <ConfirmDialog
          title={text.deleteTitle(detail.name)}
          message={text.deleteMessage(detail.current_version)}
          confirmLabel={text.delete}
          requireTypedText={detail.name}
          onCancel={() => setDialog(null)}
          onConfirm={() => {
            setDialog(null);
            void api.remove(layoutId).then(
              () => { showToast(text.deleted); navigate(backTo); },
              (err) => showToast(toErrorMessage(err, strings.common.error), "error"),
            );
          }}
        />
      )}
      {dialog === "duplicate" && detail && (
        <ReportDuplicateDialog
          api={duplicateApi} source={{ kind: "layout", id: detail.id, name: detail.name }}
          note={dirty ? strings.reportDuplicate.unsavedNote : undefined} onClose={() => setDialog(null)} onDuplicated={openDuplicate}
        />
      )}
      {dialog === "reload" && (
        <ConfirmDialog
          title={text.reloadTitle}
          message={text.reloadMessage}
          confirmLabel={text.reload}
          onCancel={() => setDialog(null)}
          onConfirm={() => { setDialog(null); void load(); }}
        />
      )}
      {dialog === "leave" && (
        <ConfirmDialog
          title={text.leaveTitle}
          message={text.leaveMessage}
          confirmLabel={text.leaveConfirm}
          onCancel={() => setDialog(null)}
          onConfirm={() => { setDialog(null); navigate(backTo); }}
        />
      )}
    </div>
  );
}
