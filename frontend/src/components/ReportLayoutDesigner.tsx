/**
 * Module: components/ReportLayoutDesigner
 *
 * The report layout designer: where a person writes a layout as text, sees its problems and a live preview, keeps
 * the work in the layout's shared draft and publishes it as a new version. One component for an organisation's and a project's layouts over `ReportLayoutApi`.
 *
 * Responsibilities:
 * - Load a layout and show its current tree as the text view (`ReportLayoutApi.formatTree`), editable in a
 *   monospace box with block shortcuts; a layout shared from elsewhere opens read-only with a "make a copy" route.
 * - Edit the same tree in three views, switchable at any time and opening on Blocks: the block editor
 *   (`ReportLayoutBlocks`), the text view and the JSON view (the raw tree, for advanced use, with no helpers and no side
 *   panel; it is checked with the server's `validate` and a switch away from invalid JSON is refused). The block editor edits one copy of the tree, which it checks with the server's `validate` a
 *   moment after each change and uses to keep the text view's text up to date, so the preview, Save and the switch
 *   back to text all read one layout. A switch from text that has problems is refused, with the reason.
 * - Check the text a moment after typing stops (`parseText`) and list every problem by line, each jumping to its
 *   line; Save new version is available only for text that parsed cleanly and publishes the shared draft, so a
 *   concurrent save is reported (409) instead of overwritten.
 * - Keep the work in the shared draft (`useLayoutDraft`): with Autosave on (a per-person switch) the tree is written a few seconds
 *   after editing pauses, with it off Save draft writes it and Discard changes puts the editor back. The status line, the draft
 *   notice, the conflict banner and the History draft row are shared components over that one session, the same in every view.
 *   A layout with a draft opens on the draft. A version exists only once published.
 * - Offer, in one right-hand panel (`DesignerSidePanel`) shared by both views, tabs for the live preview (run on screen, or
 *   downloaded as a file in any format of the layout's family), and, in the Text view, the field picker and the widget picker, which insert at the caret, or, in the Blocks
 *   view, the selected block's form (the block editor draws it into the panel). The panel collapses to a rail; the
 *   collapsed state and the last tab of each view are remembered per person. The version history and comparison are a
 *   second main tab.
 * - Insert a snippet (`ReportSnippetPicker`) from either view and report what the server did as a toast (`useSnippetToast`). In
 *   the Blocks view the editor places the blocks itself (Ctrl+Z undoes them); in the Text view the draft is read as a
 *   layout, the server inserts the snippet at the start or end of it and the text is written again from the result,
 *   with an Undo while that text stands.
 * - Save a selection as a snippet (`ReportSaveSnippetDialog`): the selected block of the Blocks view, or the top-level blocks
 *   the Text view's selection or caret touches (the server's parse says which line each block starts on).
 * - Keep Save at the top: the view tabs, Save, the count of problems that block it and any problems the server returned
 *   on save sit in one pinned bar (`.designer-bar`); a second Save appears at the foot only when the view's content is
 *   taller than the window (`useTallerThanViewport`). Both are the same button over the same `saving` state.
 * - Warn before leaving with changes the draft does not hold (the Back link and the browser's own unload prompt): with autosave on
 *   that is only while a write is pending or has failed.
 *
 * Design decisions: the text view is the only editing surface here and the server the only parser, so the client
 * holds no block model that could drift from the tree (the WYSIWYG editor later edits the same tree). The saved
 * text is the author's own, not re-formatted, so Save never reflows what they typed. Pickers only insert text.
 * What the server holds (the draft's tree, else the saved version's) is the baseline for "unsaved"; the text view,
 * opened and not typed in, is never written back, so merely looking at a layout cannot create a draft.
 */
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  conflictVersion, draftSummary, LAYOUT_FAMILY_LABEL, LAYOUT_ORIGIN_LABEL, reportLayoutPath, treeProblems,
  type BlockCatalogue, type ReportFieldCatalogue, type ReportFontChoice, type ReportLayoutApi, type ReportLayoutDetail,
  type ReportSnippet, type ReportWidget,
  type SnippetApplyResult, type TextParseResult, type TreeCheck,
} from "../api/reportLayouts";
import { reportDuplicateApi, type DuplicateResult, type ReportDuplicateApi } from "../api/reportDuplicate";
import { reportSnippetStoreApi, type ReportSnippetStoreApi, type SnippetSelection } from "../api/reportSnippets";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { DRAFT_AUTOSAVE_DELAY_MS, useLayoutDraft } from "../hooks/useLayoutDraft";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { useSnippetToast } from "../hooks/useSnippetToast";
import { useTallerThanViewport } from "../hooks/useTallerThanViewport";
import { useUiPreference } from "../hooks/useUiPreference";
import {
  aliasesInScope, asBlock, insertAt, insertionRange, lineOfOffset, offsetOfLine,
} from "../utils/reportLayoutText";
import type { ColourContext } from "../utils/reportColours";
import { parseTreeJson, stableJson, treeToJson, type Tree } from "../utils/reportLayoutTree";
import { selectionFromLines } from "../utils/reportSnippetSelection";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { Badge } from "./Badge";
import { ConfirmDialog } from "./ConfirmDialog";
import { DesignerSidePanel } from "./DesignerSidePanel";
import { LayoutDraftCompare } from "./LayoutDraftCompare";
import { LayoutDraftConflict } from "./LayoutDraftConflict";
import { LayoutDraftNotice } from "./LayoutDraftNotice";
import { LayoutDraftStatus } from "./LayoutDraftStatus";
import { ReportDuplicateDialog } from "./ReportDuplicateDialog";
import { ReportLayoutBlockToolbar } from "./ReportLayoutBlockToolbar";
import { ReportLayoutFieldPicker } from "./ReportLayoutFieldPicker";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";
import { ReportLayoutHistory } from "./ReportLayoutHistory";
import { ReportLayoutPageSetup } from "./ReportLayoutPageSetup";
import { ReportLayoutPreviewPanel } from "./ReportLayoutPreviewPanel";
import { ReportLayoutWidgetPicker } from "./ReportLayoutWidgetPicker";
import { ReportSaveSnippetDialog } from "./ReportSaveSnippetDialog";
import { ReportSnippetMenu } from "./ReportSnippetMenu";
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

type EditView = "blocks" | "text" | "json";
/** The view that edits the tree through the block editor. */
const isTreeView = (view: EditView) => view === "blocks";
type AsideTab = "block" | "preview" | "fields" | "widgets";
type Dialog =
  | "details" | "delete" | "reload" | "leave" | "duplicate" | "snippet" | "save-snippet" | "discard-draft" | "discard-changes" | "compare";

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

/** The outcome of checking one exact tree read from the JSON view. */
interface JsonChecked {
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
 * @param autosaveDelayMs How long editing must pause before the draft is written (stories shorten it).
 */
export function ReportLayoutDesigner({
  api, layoutId, backTo, projectOptions, duplicateApi: duplicateApiProp, snippetApi: snippetApiProp,
  autosaveDelayMs = DRAFT_AUTOSAVE_DELAY_MS,
}: {
  api: ReportLayoutApi;
  layoutId: string;
  backTo: string;
  projectOptions?: { value: string; label: string }[];
  /** The calls that duplicate this layout; the live ones for the layout's scope when omitted. */
  duplicateApi?: ReportDuplicateApi;
  /** The calls that save a snippet; the live ones for the layout's scope when omitted. */
  snippetApi?: ReportSnippetStoreApi;
  autosaveDelayMs?: number;
}) {
  const strings = useStrings();
  const text = strings.reportLayouts;
  const draftText = strings.layoutDraft;
  const outline = strings.reportOutline;
  const { showToast } = useToast();
  const navigate = useNavigate();
  const duplicateApi = useMemo(() => duplicateApiProp ?? reportDuplicateApi(api.scope), [duplicateApiProp, api.scope]);
  const snippetStore = useMemo(() => snippetApiProp ?? reportSnippetStoreApi(api.scope), [snippetApiProp, api.scope]);
  const beginCheck = useRequestSequence();

  const [detail, setDetail] = useState<ReportLayoutDetail | null>(null);
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  /** The text the editor opened on, with the tree (as stable JSON) it stands for: the text view is untouched while `draft` equals it. */
  const [saved, setSaved] = useState("");
  const [savedJson, setSavedJson] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [autosave, setAutosave] = useUiPreference<boolean>("report_designer_autosave", true);
  /** The layout opened with a draft: the notice stays until the draft is published or discarded. */
  const [noticeShown, setNoticeShown] = useState(false);
  const [checked, setChecked] = useState<Checked | null>(null);
  const [catalogue, setCatalogue] = useState<ReportFieldCatalogue | null>(null);
  const [widgets, setWidgets] = useState<ReportWidget[] | null>(null);
  const [blockTypes, setBlockTypes] = useState<BlockCatalogue | null>(null);
  const [colours, setColours] = useState<ColourContext | undefined>(undefined);
  const [fonts, setFonts] = useState<ReportFontChoice[] | undefined>(undefined);
  const [view, setView] = useState<EditView>("blocks");
  /** The JSON view's text, written from the tree on entry and then the author's own. */
  const [jsonText, setJsonText] = useState("");
  const [jsonChecked, setJsonChecked] = useState<JsonChecked | null>(null);
  /** The tree the block editor edits, and the tree it started from (so a switch back leaves unedited text alone). */
  const [blockTree, setBlockTree] = useState<Tree | null>(null);
  const [enteredTree, setEnteredTree] = useState<Tree | null>(null);
  const [treeChecked, setTreeChecked] = useState<TreeChecked | null>(null);
  /** The tree whose text view is in `draft`: the preview runs on the text, so it waits until the text is for the tree on screen. */
  const [textFor, setTextFor] = useState<Tree | null>(null);
  const [viewNote, setViewNote] = useState<string | null>(null);
  const [toolsFailed, setToolsFailed] = useState(false);
  const [tab, setTab] = useState<MainTab>("design");
  // The last tab of each view is remembered per person; a block being selected also brings the Block tab forward, which is not a choice to remember.
  const [storedBlocksTab, setStoredBlocksTab] = useUiPreference<string>("report_designer_tab_blocks", "block");
  const [storedTextTab, setStoredTextTab] = useUiPreference<string>("report_designer_tab_text", "preview");
  const [blocksTab, setBlocksTab] = useState<AsideTab>(storedBlocksTab === "preview" ? "preview" : "block");
  const [textTab, setTextTab] = useState<AsideTab>(storedTextTab === "fields" || storedTextTab === "widgets" ? storedTextTab : "preview");
  const [panelFolded, setPanelFolded] = useUiPreference<boolean>("report_designer_panel_collapsed", false);
  /** The element the block editor draws the selected block's form into (inside the panel's Block tab). */
  const [inspectorHost, setInspectorHost] = useState<HTMLElement | null>(null);
  /** The view's content (not the save bars): when it is taller than the window the foot offers a second Save. */
  const [content, setContent] = useState<HTMLElement | null>(null);
  const longContent = useTallerThanViewport(content);
  const [saving, setSaving] = useState(false);
  const [saveProblems, setSaveProblems] = useState<string[]>([]);
  const [conflict, setConflict] = useState<number | null>(null);
  const [caretLine, setCaretLine] = useState(0);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  /** The tree the Text view's snippet dialog applies to (the draft as read when the dialog opened). */
  const [snippetTree, setSnippetTree] = useState<Tree | null>(null);
  const snippetToast = useSnippetToast();
  /** The selection the Save as snippet dialog saves. */
  const [toSave, setToSave] = useState<SnippetToSave | null>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const pendingCaret = useRef<number | null>(null);
  /** Whether the author has put the caret in the text; until then insertions go to the end, not the untouched start. */
  const caretPlaced = useRef(false);

  // In the JSON view: read the text as it stands.
  const jsonParsed = useMemo(() => parseTreeJson(jsonText), [jsonText]);
  const current = checked?.text === draft ? checked : null;

  // What the draft would be written from: the tree the active view holds, and why it cannot be stored when it holds none.
  const family = detail?.family;
  let editorTree: Tree | null = null;
  let unreadable: string | null = null;
  let checking = false;
  if (view === "json") {
    if (jsonParsed.tree === null) unreadable = draftText.reasonJson;
    else if (jsonParsed.tree.family !== family) unreadable = draftText.reasonWrongKind;
    else editorTree = jsonParsed.tree;
  } else if (isTreeView(view)) {
    editorTree = blockTree;
  } else if (current === null) {
    checking = draft !== saved;
  } else if (current.result === null) {
    unreadable = draftText.reasonError;
  } else if (!current.result.ok || current.result.tree === null) {
    const first = current.result.errors[0];
    unreadable = first ? draftText.reasonLine(first.line) : draftText.reasonError;
  } else if (current.result.tree.family !== family) {
    unreadable = draftText.reasonWrongKind;
  } else {
    editorTree = current.result.tree;
  }
  const session = useLayoutDraft({
    api, layoutId, enabled: detail !== null && detail.editable && conflict === null, tree: editorTree, unreadable, checking,
    unchangedFrom: view === "text" && draft === saved ? savedJson : null, autosave, delayMs: autosaveDelayMs, onVersionConflict: setConflict,
  });

  const startDraft = session.start;
  const load = useCallback(async () => {
    try {
      const loaded = await api.get(layoutId);
      // A layout with a draft opens on the draft (only a scope that owns the layout sees one).
      const mine = loaded.editable && loaded.draft ? await api.draft(layoutId) : null;
      const tree = mine ? mine.tree : loaded.current.tree;
      const written = await api.formatTree(tree);
      setDetail(loaded);
      setSaved(written);
      setSavedJson(stableJson(tree));
      setDraft(written);
      setView("blocks");
      setBlockTree(tree);
      setEnteredTree(tree);
      setTextFor(tree);
      setTreeChecked(null);
      setViewNote(null);
      setChecked(null);
      setConflict(null);
      setSaveProblems([]);
      setLoadFailed(null);
      setNoticeShown(mine !== null);
      startDraft({ tree, currentVersion: loaded.current_version, summary: mine ? draftSummary(mine) : null });
    } catch (err) {
      setLoadFailed(toErrorMessage(err, strings.common.error));
    }
  }, [api, layoutId, strings.common.error, startDraft]);

  const loadTools = useCallback(async () => {
    try {
      const [fields, parts, blocks] = await Promise.all([api.fields(), api.widgets(), api.blocks()]);
      setCatalogue(fields);
      setWidgets(parts);
      setBlockTypes(blocks);
      // The colours are a convenience: a failure leaves the stock choices rather than blocking the designer.
      setColours(await (api.colours?.() ?? Promise.resolve(undefined)).catch(() => undefined));
      setFonts(await (api.fonts?.() ?? Promise.resolve(undefined)).catch(() => undefined));
      setToolsFailed(false);
    } catch {
      setToolsFailed(true);
    }
  }, [api]);

  useLoadOnChange(load, [api.scope.kind, api.scope.id, layoutId]);
  useLoadOnChange(loadTools, [api.scope.kind, api.scope.id]);

  const loaded = detail !== null;

  // Check the text once typing pauses; a response for text that has since changed is dropped. Opening the view checks the text
  // it shows, which may be unchanged since the last check was cleared.
  useEffect(() => {
    if (!loaded || view !== "text") return;
    let left = false;
    const timer = setTimeout(() => {
      const isLatest = beginCheck();
      api.parseText(draft).then(
        (result) => { if (isLatest() && !left) setChecked({ text: draft, result }); },
        () => { if (isLatest() && !left) setChecked({ text: draft, result: null }); },
      );
    }, TEXT_CHECK_DELAY_MS);
    return () => { left = true; clearTimeout(timer); };
  }, [draft, loaded, view, api, beginCheck]);

  // In the block editor: check the tree once editing pauses, and keep the text view's text in step with it.
  useEffect(() => {
    if (!loaded || !isTreeView(view) || blockTree === null) return;
    const tree = blockTree;
    // A check still in flight when the author leaves the view (or edits again) must not write over what they type next.
    let left = false;
    const timer = setTimeout(() => {
      const isLatest = beginCheck();
      api.validate(tree).then(
        async (result) => {
          if (!isLatest() || left) return;
          setTreeChecked({ tree, result });
          if (result.ok) {
            const written = await api.formatTree(tree);
            if (isLatest() && !left) {
              setDraft(written);
              setTextFor(tree);
            }
          }
        },
        () => { if (isLatest() && !left) setTreeChecked({ tree, result: null }); },
      );
    }, TEXT_CHECK_DELAY_MS);
    return () => { left = true; clearTimeout(timer); };
  }, [blockTree, view, loaded, api, beginCheck]);

  // In the JSON view: check the tree the text holds once editing pauses.
  useEffect(() => {
    const tree = jsonParsed.tree;
    if (!loaded || view !== "json" || tree === null) return;
    let left = false;
    const timer = setTimeout(() => {
      const isLatest = beginCheck();
      api.validate(tree).then(
        (result) => { if (isLatest() && !left) setJsonChecked({ tree, result }); },
        () => { if (isLatest() && !left) setJsonChecked({ tree, result: null }); },
      );
    }, TEXT_CHECK_DELAY_MS);
    return () => { left = true; clearTimeout(timer); };
  }, [jsonParsed, view, loaded, api, beginCheck]);

  // Put the caret where an insertion left it, once the new text is in the box.
  useLayoutEffect(() => {
    const at = pendingCaret.current;
    const el = editor.current;
    if (at === null || !el) return;
    pendingCaret.current = null;
    el.focus();
    el.setSelectionRange(at, at);
  }, [draft]);

  /** The editor holds changes the shared draft does not (with autosave on, only while a write is pending or has failed). */
  const dirty = loaded && session.pending;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (loadFailed && !detail) return <p className="text-muted" role="alert">{loadFailed}</p>;
  if (!detail) return <Spinner />;

  const editable = detail.editable;
  const wrongKind = current?.result?.tree != null && current.result.tree.family !== detail.family;
  const problems = [
    ...(current?.result && !current.result.ok ? current.result.errors : []),
    // The server parses text without knowing the layout, so a first line naming the other kind is caught here.
    ...(wrongKind ? [{ line: 1, column: null, message: text.familyMismatch(LAYOUT_FAMILY_LABEL[detail.family].toLowerCase()) }] : []),
  ];
  const blockCurrent = treeChecked !== null && treeChecked.tree === blockTree ? treeChecked : null;
  const blockProblems = blockCurrent?.result?.errors ?? [];
  const jsonCurrent = jsonChecked !== null && jsonChecked.tree === jsonParsed.tree ? jsonChecked : null;
  const jsonWrongKind = jsonParsed.tree !== null && jsonParsed.tree.family !== detail.family;
  /** What is wrong with the JSON, as lines: the parser's own message, the wrong kind, or the server's problems by path. */
  const jsonProblems = jsonParsed.tree === null
    ? [jsonParsed.notObject ? outline.jsonNotObject : jsonParsed.error]
    : [
      ...(jsonWrongKind ? [outline.jsonWrongKind(LAYOUT_FAMILY_LABEL[detail.family].toLowerCase())] : []),
      ...(jsonCurrent?.result && !jsonCurrent.result.ok ? jsonCurrent.result.errors.map((p) => text.treeProblem(p.path, p.message)) : []),
    ];
  const jsonValid = jsonCurrent?.result?.ok === true && !jsonWrongKind;
  const valid = view === "json"
    ? jsonValid
    : isTreeView(view)
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
      // Undo puts the old text back only while the inserted text still stands, so it never discards later typing.
      const before = draft;
      snippetToast.announce(
        { name: snippet.name, changes: result.changes, problemsElsewhere: result.problems_elsewhere },
        () => {
          setDraft((current) => (current === written ? before : current));
          setChecked(null);
        },
      );
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
   * Reads the tree the JSON view holds for a switch away from it: it must be JSON, the right kind of layout and pass the
   * server's check. A refusal puts its reason in the view note and resolves to `null`.
   */
  async function treeFromJson(): Promise<Tree | null> {
    const tree = jsonParsed.tree;
    if (tree === null || tree.family !== detail?.family) {
      setViewNote(tree === null ? (jsonParsed.notObject ? outline.jsonNotObject : jsonParsed.error) : outline.jsonNeedsFixes);
      return null;
    }
    let result: TreeCheck | null = jsonCurrent?.result ?? null;
    if (result === null) {
      try {
        result = await api.validate(tree);
      } catch {
        result = null;
      }
    }
    if (result?.ok !== true) {
      setViewNote(outline.jsonNeedsFixes);
      return null;
    }
    return tree;
  }

  /**
   * Changes the editing view. A switch from the text needs text that reads cleanly; a switch from the JSON needs a tree that
   * checks cleanly; the blocks may be shown as text or JSON whatever their problems. A refusal says why and stays where it is.
   * The text keeps the author's own wording when the tree has not changed since it was read from it.
   */
  async function switchView(next: EditView) {
    if (next === view) return;
    setViewNote(null);
    snippetToast.clear();
    let tree: Tree | null;
    if (view === "blocks") {
      tree = blockTree;
    } else if (view === "json") {
      tree = await treeFromJson();
      if (tree === null) return;
    } else {
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
        setViewNote(next === "json" ? outline.jsonNeedsTextFixes : outline.outlineNeedsFixes);
        return;
      }
      setEnteredTree(tree);
    }
    if (tree === null) return;
    if (next === "text") {
      if (view !== "text" && (enteredTree === null || stableJson(tree) !== stableJson(enteredTree))) {
        try {
          setDraft(await api.formatTree(tree));
        } catch {
          setViewNote(outline.outlineFormatFailed);
          return;
        }
      }
      setChecked(null);
    } else if (next === "blocks") {
      if (view === "json") {
        try {
          setDraft(await api.formatTree(tree));
        } catch {
          setViewNote(outline.outlineFormatFailed);
          return;
        }
        setEnteredTree(tree);
      }
      setBlockTree(tree);
      setTextFor(tree);
      setTreeChecked(null);
    } else {
      setJsonText(treeToJson(tree));
      setJsonChecked(null);
    }
    setView(next);
  }

  /** Publishes the draft (writing what is pending first) as a new version with `note`; resolves to whether it was done. */
  async function save(note: string): Promise<boolean> {
    if (!detail) return false;
    setSaving(true);
    setSaveProblems([]);
    try {
      const result = await session.publish(note);
      if (result === null) return false;
      setNoticeShown(false);
      if (result === "unchanged") {
        showToast(text.noChanges);
        return true;
      }
      showToast(text.saved(result.current_version));
      const tree = result.current.tree;
      setDetail(result);
      const written = view !== "text" ? await api.formatTree(tree) : draft;
      setSaved(written);
      setSavedJson(stableJson(tree));
      if (view !== "text") {
        setDraft(written);
        setEnteredTree(tree);
        setTextFor(tree);
        setBlockTree(tree);
      }
      session.start({ tree, summary: null, currentVersion: result.current_version });
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

  /** Writes the draft now (autosave off) and says so. */
  async function saveDraft() {
    if (await session.saveNow()) showToast(draftText.draftSavedToast);
    else showToast(draftText.draftSaveFailed, "error");
  }

  /** Turns autosave on or off for this person; turning it on writes what is pending at once. */
  function chooseAutosave(next: boolean) {
    setAutosave(next);
    if (next) void session.saveNow();
  }

  /** Discards the shared draft for everyone (one already gone is what was asked for); resolves to whether it is gone. */
  async function dropDraft(): Promise<boolean> {
    try {
      await api.discardDraft(layoutId);
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return true;
      showToast(toErrorMessage(err, draftText.discardFailed), "error");
      return false;
    }
  }

  /** Discards the shared draft and opens the layout at its latest saved version. */
  async function discardDraft() {
    setDialog(null);
    if (!(await dropDraft())) return;
    showToast(draftText.draftDiscarded);
    await load();
  }

  /** Replaces the editor with the latest saved version, which discards the draft (it was begun on an older version). */
  async function reloadLatest() {
    setDialog(null);
    if (session.summary !== null && !(await dropDraft())) return;
    await load();
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

  const blockingCount = view === "json" ? jsonProblems.length : isTreeView(view) ? blockProblems.length : problems.length;
  // The text view, opened and not typed in, stands for the tree it opened on; the other views compare their tree.
  const publishedJson = stableJson(detail.current.tree);
  const sameAsPublished = view === "text"
    ? draft === saved && savedJson === publishedJson
    : editorTree !== null && stableJson(editorTree) === publishedJson;
  const saveButton = (
    <SaveVersionButton
      disabled={!valid || sameAsPublished} saving={saving} onSave={save} title={draftText.publishTooltip(detail.current_version + 1)}
    />
  );
  const draftControls = editable && (
    <LayoutDraftStatus
      autosave={autosave} onAutosave={chooseAutosave} savedAt={session.summary?.updated_at ?? null} pending={session.pending}
      saving={session.saving} failure={session.failure} unreadable={unreadable} onSaveDraft={() => void saveDraft()}
      onDiscardChanges={() => setDialog("discard-changes")}
    />
  );
  const textTools = editable && view === "text";
  const treeEditing = isTreeView(view);
  const asideTabs: TabDef<AsideTab>[] = treeEditing
    ? [{ key: "block", label: text.blockTab }, { key: "preview", label: text.previewTab }]
    : [
      { key: "preview", label: text.previewTab },
      ...(textTools ? [{ key: "fields" as const, label: text.fieldsTab }, { key: "widgets" as const, label: text.widgetsTab }] : []),
    ];
  const wanted = treeEditing ? blocksTab : textTab;
  const asideActive = asideTabs.some((tab) => tab.key === wanted) ? wanted : asideTabs[0].key;
  function chooseAside(next: AsideTab) {
    if (treeEditing) {
      setBlocksTab(next);
      setStoredBlocksTab(next);
    } else {
      setTextTab(next);
      setStoredTextTab(next);
    }
  }
  const preview = (
    <ReportLayoutPreviewPanel
      api={api} layoutId={layoutId} family={detail.family} text={draft} name={detail.name} disabled={!valid || (treeEditing && textFor !== blockTree)} projectOptions={projectOptions}
    />
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
            draft={session.summary ? { summary: session.summary, onDiscard: editable ? () => setDialog("discard-draft") : undefined } : null}
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
          className={`layout-designer${treeEditing ? " layout-designer--blocks" : ""}${view === "json" ? " layout-designer--single" : ""}${panelFolded ? " layout-designer--panel-folded" : ""}`}
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
                <div className="row">
                  <button type="button" className="btn" onClick={() => setDialog("reload")}>{text.reload}</button>
                  <button type="button" className="btn" onClick={() => { session.rebase(conflict); setConflict(null); }}>{draftText.rebase(conflict)}</button>
                </div>
              </div>
            )}
            {session.conflict && <LayoutDraftConflict draft={session.conflict.draft} onLoadTheirs={() => void load()} onKeepMine={session.keepMine} />}
            {editable && noticeShown && session.summary && (
              <LayoutDraftNotice
                summary={session.summary} currentVersion={detail.current_version}
                onShowSaved={() => setDialog("compare")} onDiscard={() => setDialog("discard-draft")}
              />
            )}
            <div className="designer-bar">
              <div className="designer-bar__row">
                <div className="designer-bar__tabs">
                  <Tabs<EditView>
                    idPrefix="layout-view"
                    tabs={[{ key: "blocks", label: outline.outlineView }, { key: "text", label: outline.textView }, { key: "json", label: outline.jsonView }]}
                    active={view} onChange={(next) => void switchView(next)}
                  />
                </div>
                {editable && (
                  <div className="designer-bar__save">
                    {!valid && blockingCount > 0 && <span role="status" style={{ color: "var(--color-danger)" }}>{text.saveBlocked(blockingCount)}</span>}
                    {draftControls}
                    {saveButton}
                  </div>
                )}
              </div>
              {saveProblems.length > 0 && (
                <ul className="layout-problems" role="alert">
                  {saveProblems.map((problem, index) => <li key={index} style={{ color: "var(--color-danger)" }}>{problem}</li>)}
                </ul>
              )}
            </div>
            <div ref={setContent} className="stack">
            {viewNote && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{viewNote}</p>}
            {view === "text" && (
              <div {...tabPanelProps("layout-view", "text")} className="stack">
              {editable && (
                <div className="row" style={{ alignItems: "center", gap: "var(--space-3)" }}>
                  <ReportLayoutBlockToolbar family={detail.family} onInsert={(snippet) => insert(snippet, true)} />
                  {blockTypes && <ReportSnippetMenu onInsert={() => void openTextSnippets()} onSave={() => void openTextSave()} />}
                  <ReportLayoutPageSetup
                    text={draft} onChange={setDraft} images={{ library: api.images, scope: api.scope.kind }}
                    placeholders={catalogue?.placeholders} look={{ fonts, colours }} newLayout={detail.current_version <= 1}
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
              </div>
              </div>
            )}
            {view === "json" && (
              <div {...tabPanelProps("layout-view", "json")} className="stack">
                <p className="text-muted" role="note" style={{ margin: 0 }}>{outline.jsonNote}</p>
                <AutoGrowTextarea
                  className="input layout-editor"
                  value={jsonText}
                  onChange={setJsonText}
                  rows={16}
                  maxVisibleLines={EDITOR_MAX_LINES}
                  aria-label={outline.jsonLabel}
                  spellCheck={false}
                  readOnly={!editable}
                />
                <div aria-live="polite">
                  {jsonParsed.tree !== null && jsonCurrent === null && <span className="text-muted">{outline.outlineChecking}</span>}
                  {jsonCurrent && jsonCurrent.result === null && <span role="alert" style={{ color: "var(--color-danger)" }}>{strings.common.error}</span>}
                  {jsonValid && <span className="text-muted">{outline.outlineNoProblems}</span>}
                  {jsonProblems.length > 0 && (
                    <div className="stack" style={{ gap: "var(--space-2)" }}>
                      <strong>{outline.jsonProblemsTitle(jsonProblems.length)}</strong>
                      <ul className="layout-problems" aria-label={outline.jsonProblemsTitle(jsonProblems.length)}>
                        {jsonProblems.map((problem, index) => <li key={index}>{problem}</li>)}
                      </ul>
                    </div>
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
                        widgets={widgets} problems={blockProblems} readOnly={!editable}
                        inspectorHost={inspectorHost} onInspect={() => setBlocksTab("block")}
                        images={{ library: api.images, scope: api.scope.kind }} colours={colours} fonts={fonts}
                        newLayout={detail.current_version <= 1}
                        snippets={{
                          api,
                          onInserted: (notice) => snippetToast.announce(notice),
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
                  </>
                ) : toolsFailed ? <p className="text-muted" role="alert">{outline.outlineLoadFailed}</p> : <Spinner />}
              </div>
            )}
            </div>
            {editable && longContent && <div className="row">{saveButton}</div>}
          </div>

          {view !== "json" && <DesignerSidePanel<AsideTab>
            label={text.asideLabel} idPrefix="layout-designer-tools" tabs={asideTabs} active={asideActive} onChange={chooseAside}
            collapsed={panelFolded} onCollapsedChange={setPanelFolded}
          >
            {treeEditing && (
              <div {...tabPanelProps("layout-designer-tools", "block")} hidden={asideActive !== "block"}>
                <div ref={setInspectorHost} />
              </div>
            )}
            <div {...tabPanelProps("layout-designer-tools", "preview")} hidden={asideActive !== "preview"}>
              {preview}
            </div>
            {textTools && toolsFailed && asideActive !== "preview" && <p className="text-muted" role="alert">{text.loadToolsFailed}</p>}
            {textTools && (
              <div {...tabPanelProps("layout-designer-tools", "fields")} hidden={asideActive !== "fields"}>
                {catalogue ? (
                  <ReportLayoutFieldPicker catalogue={catalogue} aliases={aliases} onInsert={(snippet) => insert(snippet, false)} />
                ) : !toolsFailed && <Spinner />}
              </div>
            )}
            {textTools && (
              <div {...tabPanelProps("layout-designer-tools", "widgets")} hidden={asideActive !== "widgets"}>
                {widgets ? (
                  <ReportLayoutWidgetPicker widgets={widgets} onInsert={(line) => insert(line, true)} />
                ) : !toolsFailed && <Spinner />}
              </div>
            )}
          </DesignerSidePanel>}
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
      {dialog === "details" && (
        <ReportLayoutFormModal
          api={api}
          layout={detail}
          onClose={() => setDialog(null)}
          onSaved={(updated) => {
            showToast(text.detailsSaved);
            setDetail({
              ...detail, name: updated.name, description: updated.description, folder: updated.folder,
              updated_at: updated.updated_at,
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
          note={sameAsPublished ? undefined : strings.reportDuplicate.unsavedNote} onClose={() => setDialog(null)} onDuplicated={openDuplicate}
        />
      )}
      {dialog === "compare" && (
        <LayoutDraftCompare api={api} layoutId={layoutId} saved={{ version: detail.current_version, tree: detail.current.tree }} onClose={() => setDialog(null)} />
      )}
      {dialog === "discard-draft" && (
        <ConfirmDialog
          title={draftText.discardDraftTitle}
          message={draftText.discardDraftMessage(detail.current_version)}
          confirmLabel={draftText.discardDraft}
          onCancel={() => setDialog(null)}
          onConfirm={() => void discardDraft()}
        />
      )}
      {dialog === "discard-changes" && (
        <ConfirmDialog
          title={draftText.discardChangesTitle}
          message={draftText.discardChangesMessage(session.summary !== null)}
          confirmLabel={draftText.discardChanges}
          onCancel={() => setDialog(null)}
          onConfirm={() => { setDialog(null); showToast(draftText.changesDiscarded); void load(); }}
        />
      )}
      {dialog === "reload" && (
        <ConfirmDialog
          title={text.reloadTitle}
          message={text.reloadMessage}
          confirmLabel={text.reload}
          onCancel={() => setDialog(null)}
          onConfirm={() => void reloadLatest()}
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
