/**
 * Module: components/ReportLayoutDesigner
 *
 * The report layout designer: where a person writes a layout as text, sees its problems and a live preview, and
 * saves it as a new version. One component for an organisation's and a project's layouts over `ReportLayoutApi`.
 *
 * Responsibilities:
 * - Load a layout and show its current tree as the text view (`ReportLayoutApi.formatTree`), editable in a
 *   monospace box with block shortcuts; a layout shared from elsewhere opens read-only with a "make a copy" route.
 * - Edit the same tree in three views, switchable at any time: the text view, the block outline
 *   (`ReportLayoutOutline`) and, for a document layout, the document (`ReportLayoutRichText`). The two tree views
 *   edit one copy of the tree, which it checks with the server's `validate` a moment after each change and uses to
 *   keep the text view's text up to date, so the preview, Save and the switch back to text all read one layout.
 *   Moving between the outline and the document needs no conversion. A view that cannot show the layout as it
 *   stands (text with problems; a tree the document cannot show without changing it) refuses the switch, with the reason.
 * - Check the text a moment after typing stops (`parseText`) and list every problem by line, each jumping to its
 *   line; Save is available only for text that parsed cleanly, and sends the parsed tree with the version the
 *   author started from, so a concurrent save is reported (409) instead of overwritten.
 * - Offer, beside the editor, the live preview, the field picker and the widget picker, which insert at the caret;
 *   and, on a second tab, the version history and comparison.
 * - Warn before leaving with unsaved changes (the Back link and the browser's own unload prompt).
 *
 * Design decisions: the text view is the only editing surface here and the server the only parser, so the client
 * holds no block model that could drift from the tree (the WYSIWYG editor later edits the same tree). The saved
 * text is the author's own, not re-formatted, so Save never reflows what they typed. Pickers only insert text.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  conflictVersion, copyReportLayout, LAYOUT_FAMILY_LABEL, LAYOUT_ORIGIN_LABEL, reportLayoutPath, treeProblems,
  type BlockCatalogue, type ReportFieldCatalogue, type ReportLayoutApi, type ReportLayoutDetail, type ReportWidget,
  type TextParseResult, type TreeCheck,
} from "../api/reportLayouts";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRequestSequence } from "../hooks/useRequestSequence";
import {
  aliasesInScope, asBlock, BLOCK_SNIPPETS, insertAt, insertionRange, lineOfOffset, offsetOfLine,
} from "../utils/reportLayoutText";
import { NotRepresentableError, treeToDoc } from "../utils/reportLayoutDoc";
import { stableJson, type Tree } from "../utils/reportLayoutTree";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { TextField } from "./FormFields";
import { ReportLayoutFieldPicker } from "./ReportLayoutFieldPicker";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";
import { ReportLayoutHistory } from "./ReportLayoutHistory";
import { ReportLayoutOutline } from "./ReportLayoutOutline";
import { ReportLayoutRichText } from "./ReportLayoutRichText";
import { ReportLayoutPreviewPanel } from "./ReportLayoutPreviewPanel";
import { ReportLayoutWidgetPicker } from "./ReportLayoutWidgetPicker";
import { RecordHeader } from "./RecordHeader";
import { Spinner } from "./Spinner";
import { Tabs, tabPanelProps, type TabDef } from "./Tabs";

/** How long typing must pause before the text is checked. */
export const TEXT_CHECK_DELAY_MS = 400;
/** Tallest the editor grows before it scrolls, in lines. */
const EDITOR_MAX_LINES = 40;

type MainTab = "design" | "history";
type EditView = "text" | "outline" | "document";
/** The views that edit the tree itself (the text view edits text). */
const isTreeView = (view: EditView) => view !== "text";
type AsideTab = "preview" | "fields" | "widgets";
type Dialog = "details" | "delete" | "reload" | "leave";

/** The outcome of checking one exact outline tree. */
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
  api, layoutId, backTo, projectOptions,
}: {
  api: ReportLayoutApi;
  layoutId: string;
  backTo: string;
  projectOptions?: { value: string; label: string }[];
}) {
  const strings = useStrings();
  const text = strings.reportLayouts;
  const outline = strings.reportOutline;
  const { showToast } = useToast();
  const navigate = useNavigate();
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
  /** The tree the outline edits, and the tree it started from (so a switch back leaves unedited text alone). */
  const [outlineTree, setOutlineTree] = useState<Tree | null>(null);
  const [enteredTree, setEnteredTree] = useState<Tree | null>(null);
  const [treeChecked, setTreeChecked] = useState<TreeChecked | null>(null);
  /** The tree whose text view is in `draft`: the preview runs on the text, so it waits until the text is for the tree on screen. */
  const [textFor, setTextFor] = useState<Tree | null>(null);
  const [viewNote, setViewNote] = useState<string | null>(null);
  const [toolsFailed, setToolsFailed] = useState(false);
  const [tab, setTab] = useState<MainTab>("design");
  const [aside, setAside] = useState<AsideTab>("preview");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<number | null>(null);
  const [caretLine, setCaretLine] = useState(0);
  const [dialog, setDialog] = useState<Dialog | null>(null);
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
      setOutlineTree(null);
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

  // In the outline: check the tree once editing pauses, and keep the text view's text in step with it.
  useEffect(() => {
    if (!loaded || !isTreeView(view) || outlineTree === null) return;
    const tree = outlineTree;
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
  }, [outlineTree, view, loaded, api, beginCheck]);

  // Put the caret where an insertion left it, once the new text is in the box.
  useLayoutEffect(() => {
    const at = pendingCaret.current;
    const el = editor.current;
    if (at === null || !el) return;
    pendingCaret.current = null;
    el.focus();
    el.setSelectionRange(at, at);
  }, [draft]);

  const outlineChanged = isTreeView(view) && outlineTree !== null && detail !== null && stableJson(outlineTree) !== stableJson(detail.current.tree);
  const dirty = loaded && (isTreeView(view) ? outlineChanged : draft !== saved);
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
  const outlineCurrent = treeChecked !== null && treeChecked.tree === outlineTree ? treeChecked : null;
  const outlineProblems = outlineCurrent?.result?.errors ?? [];
  const valid = isTreeView(view)
    ? outlineCurrent?.result?.ok === true
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
    if (next === "text") {
      if (outlineTree !== null && enteredTree !== null && stableJson(outlineTree) !== stableJson(enteredTree)) {
        try {
          setDraft(await api.formatTree(outlineTree));
        } catch {
          setViewNote(strings.reportOutline.outlineFormatFailed);
          return;
        }
      }
      setChecked(null);
      setView("text");
      return;
    }
    let tree = outlineTree;
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
    if (next === "document" && tree && blockTypes) {
      try {
        treeToDoc(tree, blockTypes.blocks);
      } catch (err) {
        if (!(err instanceof NotRepresentableError)) throw err;
        setViewNote(strings.reportOutline.richNotShown(`${err.path}: ${err.message}`));
        return;
      }
    }
    if (view === "text") {
      setOutlineTree(tree);
      setEnteredTree(tree);
      setTextFor(tree);
      setTreeChecked(null);
    }
    setView(next);
  }

  async function save() {
    const tree = isTreeView(view) ? outlineCurrent?.tree : current?.result?.tree;
    if (!tree || !detail) return;
    setSaving(true);
    setSaveProblems([]);
    try {
      const result = await api.save(layoutId, { tree, base_version: detail.current_version, comment: note.trim() });
      showToast(result.current_version === detail.current_version ? text.noChanges : text.saved(result.current_version));
      setDetail(result);
      const written = isTreeView(view) ? await api.formatTree(tree) : draft;
      setSaved(written);
      if (isTreeView(view)) {
        setDraft(written);
        setEnteredTree(tree);
        setTextFor(tree);
      }
      setNote("");
    } catch (err) {
      const newer = conflictVersion(err);
      const found = treeProblems(err);
      if (newer !== null) setConflict(newer);
      else if (found.length > 0) setSaveProblems(found.map((p) => text.treeProblem(p.path, p.message)));
      else showToast(toErrorMessage(err, text.saveFailed), "error");
    } finally {
      setSaving(false);
    }
  }

  function leave() {
    if (dirty) setDialog("leave");
    else navigate(backTo);
  }

  async function makeCopy() {
    try {
      const created = await copyReportLayout(api, detail as ReportLayoutDetail, text.copyName(detail?.name ?? ""));
      showToast(text.copied);
      navigate(reportLayoutPath(api.scope, created.id));
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const asideTabs: TabDef<AsideTab>[] = [
    { key: "preview", label: text.previewTab },
    ...(editable && view === "text" ? [{ key: "fields" as const, label: text.fieldsTab }, { key: "widgets" as const, label: text.widgetsTab }] : []),
  ];
  const textTools = editable && view === "text";
  const blocks = BLOCK_SNIPPETS.filter((b) => b.families.includes(detail.family));

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
          { key: "copy", label: text.makeCopy, onSelect: () => void makeCopy() },
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
        <div {...tabPanelProps("layout-designer", "design")} className="layout-designer">
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
              tabs={[
                { key: "text", label: outline.textView }, { key: "outline", label: outline.outlineView },
                ...(detail.family === "document" ? [{ key: "document" as const, label: outline.documentView }] : []),
              ]}
              active={view} onChange={(next) => void switchView(next)}
            />
            {viewNote && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{viewNote}</p>}
            {view === "text" && (
              <div {...tabPanelProps("layout-view", "text")} className="stack">
              {editable && (
                <div className="row" role="toolbar" aria-label={text.insertBlock} style={{ flexWrap: "wrap" }}>
                  {blocks.map((block) => (
                    <button
                      key={block.key} type="button" className="btn btn-sm"
                      aria-label={`${text.insertBlock}: ${text.blockLabels[block.key]}`}
                      onClick={() => insert(block.text, true)}
                    >
                      {text.blockLabels[block.key]}
                    </button>
                  ))}
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
                {outlineTree && blockTypes && catalogue && widgets ? (
                  <>
                    {view === "document" ? (
                      <ReportLayoutRichText
                        tree={outlineTree} onChange={setOutlineTree} family={detail.family} blocks={blockTypes} catalogue={catalogue}
                        widgets={widgets} problems={outlineProblems} readOnly={!editable}
                      />
                    ) : (
                      <ReportLayoutOutline
                        tree={outlineTree} onChange={setOutlineTree} family={detail.family} blocks={blockTypes} catalogue={catalogue}
                        widgets={widgets} problems={outlineProblems} readOnly={!editable}
                      />
                    )}
                    <div aria-live="polite">
                      {outlineCurrent === null && <span className="text-muted">{outline.outlineChecking}</span>}
                      {outlineCurrent && outlineCurrent.result === null && <span role="alert" style={{ color: "var(--color-danger)" }}>{strings.common.error}</span>}
                      {outlineCurrent?.result?.ok === true && <span className="text-muted">{outline.outlineNoProblems}</span>}
                      {outlineProblems.length > 0 && <strong>{outline.outlineProblemsTitle(outlineProblems.length)}</strong>}
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
              <div className="row" style={{ alignItems: "flex-end" }}>
                <TextField helpNotNeeded
                  label={text.changeNoteLabel} value={note} onChange={setNote} placeholder={text.changeNotePlaceholder}
                  inputProps={{ maxLength: 500 }}
                />
                <button type="button" className="btn btn-primary" disabled={!valid || !dirty || saving} onClick={() => void save()}>
                  {text.saveVersion}
                </button>
              </div>
            )}
          </div>

          <div className="stack" aria-label={text.asideLabel} role="region">
            <Tabs<AsideTab> idPrefix="layout-designer-tools" tabs={asideTabs} active={textTools ? aside : "preview"} onChange={setAside} />
            <div {...tabPanelProps("layout-designer-tools", "preview")} hidden={textTools && aside !== "preview"}>
              <ReportLayoutPreviewPanel
                api={api} text={draft} name={detail.name} disabled={!valid || (isTreeView(view) && textFor !== outlineTree)} projectOptions={projectOptions}
              />
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
        </div>
      )}

      {dialog === "details" && (
        <ReportLayoutFormModal
          api={api}
          layout={detail}
          onClose={() => setDialog(null)}
          onSaved={(updated) => {
            showToast(text.detailsSaved);
            setDetail({ ...detail, name: updated.name, description: updated.description, updated_at: updated.updated_at });
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
