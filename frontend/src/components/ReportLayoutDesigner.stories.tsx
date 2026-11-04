import type { Meta, StoryObj } from "@storybook/react-vite";
import * as Blockly from "blockly/core";
import { expect, fn, mocked, screen, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import type { ReportLayoutApi } from "../api/reportLayouts";
import {
  buildLayoutApi, buildLayoutDetail, buildLayoutDraft, buildLayoutSummary, buildOutlineTree, fakeValidate, LAYOUT_TEXT, TEXT_CHECKED_MS,
} from "../testing/reportLayoutFixtures";
import { buildDuplicateApi } from "../testing/reportDuplicateFixtures";
import { buildFileApi } from "../testing/reportFileFixtures";
import { chooseSnippetMenuItem, snippetMenuItem } from "../testing/reportSnippetMenuHelpers";
import { buildSnippetStoreApi } from "../testing/reportSnippetStoreFixtures";
import { saveVersion } from "../testing/saveVersionHelpers";
import { buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportLayoutDesigner } from "./ReportLayoutDesigner";

/**
 * The report layout designer: the layout as text with its problems, a live preview, field and widget pickers that
 * insert at the caret, and the version history. Saving sends the parsed tree with the version it started from.
 */
const meta: Meta<typeof ReportLayoutDesigner> = {
  title: "Components/ReportLayoutDesigner",
  component: ReportLayoutDesigner,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter("/projects/project-1/report-layouts/layout-1")],
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), layoutId: "layout-1", backTo: "/projects/project-1/admin/reportSetup" },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutDesigner>;

const body = () => within(document.body);

const STATUS = "Draft status";
/** A pause short enough for a story and longer than a keystroke burst. */
const FAST_AUTOSAVE_MS = 50;
/** Signs in a person whose Autosave switch is off (the meta's router stays around it). */
const autosaveOff = () => [withStatefulAuth(buildUser({ ui_preferences: { report_designer_autosave: false } }))];

/** Types `words` at the end of the Text view's text. */
async function typeAtEnd(editor: HTMLTextAreaElement, words: string) {
  editor.focus();
  editor.setSelectionRange(editor.value.length, editor.value.length);
  await userEvent.keyboard(words);
}

/** The text editor, after opening the Text view (a layout opens on Blocks). */
async function editorOf(canvasElement: HTMLElement): Promise<HTMLTextAreaElement> {
  const canvas = within(canvasElement);
  await userEvent.click(await canvas.findByRole("tab", { name: "Text" }));
  return (await canvas.findByRole("textbox", { name: "Layout text" })) as HTMLTextAreaElement;
}

/** Puts the caret at the start of the given 1-based line and tells the editor, as a real caret move would. */
async function caretAtLine(editor: HTMLTextAreaElement, line: number) {
  const at = editor.value.split("\n").slice(0, line - 1).join("\n").length + (line > 1 ? 1 : 0);
  editor.focus();
  editor.setSelectionRange(at, at);
  await userEvent.keyboard("{ArrowRight}{ArrowLeft}");
}

export const OpensTheLayoutAsTextAndChecksIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await expect(editor.value).toBe(LAYOUT_TEXT);
    await expect(canvas.getByRole("heading", { name: "Requirements by component" })).toBeInTheDocument();
    await expect(canvas.getByText("Version 2")).toBeInTheDocument();
    await expect(await canvas.findByText("The text is valid.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
  },
};

export const ProblemsAreListedByLineAndBlockSaving: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(0, 0);
    await userEvent.keyboard("BROKEN ");
    const problem = await canvas.findByRole("button", { name: "Line 1, column 1: Unknown word BROKEN." }, { timeout: TEXT_CHECKED_MS });
    await expect(canvas.getByText("1 problem to fix")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Run preview" })).toBeDisabled();
    await userEvent.click(problem);
    await expect(editor).toHaveFocus();
    await expect(editor.selectionStart).toBe(0);
  },
};

/** A layout's kind is fixed at creation, so text declaring the other kind is a problem before the server is asked. */
export const TextDeclaringTheOtherKindIsAProblem: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await userEvent.clear(editor);
    await userEvent.type(editor, "@layout table{Enter}");
    const problem = await canvas.findByRole("button", { name: /^Line 1: This is a document layout/ }, { timeout: TEXT_CHECKED_MS });
    await expect(problem).toBeInTheDocument();
    await expect(canvas.queryByText("The text is valid.")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Run preview" })).toBeDisabled();
  },
};

export const SavingSendsTheParsedTreeAndTheVersionItStartedFrom: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.keyboard("Closing words.");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save, "Added closing words");
    await waitFor(() => expect(args.api.publishDraft).toHaveBeenCalledWith("layout-1", { draft_revision: 1, comment: "Added closing words" }));
    await expect(args.api.writeDraft).toHaveBeenCalledWith(
      "layout-1", expect.objectContaining({ base_version: 2, revision: 0, tree: expect.objectContaining({ family: "document" }) }),
    );
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
    await expect(canvas.getByText("Version 3")).toBeInTheDocument();
  },
};

/** Save sits in the pinned bar with the view tabs, and a short layout has no second one at the foot. */
export const SaveIsPinnedAtTheTopAndAShortLayoutHasOnlyThatOne: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    const bar = canvasElement.querySelector<HTMLElement>(".designer-bar");
    await expect(bar).not.toBeNull();
    await expect(within(bar as HTMLElement).getByRole("button", { name: "Save new version" })).toBeInTheDocument();
    await expect(within(bar as HTMLElement).getByRole("tab", { name: "Text" })).toBeInTheDocument();
    await expect(canvas.getAllByRole("button", { name: "Save new version" })).toHaveLength(1);
    await expect(getComputedStyle(bar as HTMLElement).position).toBe("sticky");
  },
};

/** A layout taller than the window gets a second Save at the foot; both are one button's state, so one save disables both. */
export const ALongLayoutAlsoOffersSaveAtTheFoot: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary()], {
      stateful: false,
      get: async () => buildLayoutDetail({}, `@layout document\n${Array.from({ length: 120 }, (_, i) => `\n@heading Section ${i + 1}\n`).join("")}`),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await waitFor(() => expect(canvas.getAllByRole("button", { name: "Save new version" })).toHaveLength(2));
    const [top, foot] = canvas.getAllByRole("button", { name: "Save new version" });
    await expect(canvasElement.querySelector(".designer-bar")).toContainElement(top);
    await expect(canvasElement.querySelector(".designer-bar")).not.toContainElement(foot);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.keyboard("More.");
    await waitFor(() => expect(top).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await expect(foot).toBeEnabled();
  },
};

/** A disabled Save explains itself next to the button: the count of problems stays in view with the pinned bar. */
export const TheProblemCountSitsBesideSave: Story = {
  play: async ({ canvasElement }) => {
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(0, 0);
    await userEvent.keyboard("BROKEN ");
    const bar = canvasElement.querySelector<HTMLElement>(".designer-bar") as HTMLElement;
    await within(bar).findByText("Fix 1 problem to save", undefined, { timeout: TEXT_CHECKED_MS });
    await expect(within(bar).getByRole("button", { name: "Save new version" })).toBeDisabled();
  },
};

export const SavingATreeTheServerRefusesShowsItsProblems: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary()], {
      publishDraft: async () => {
        throw new ApiError(422, "The layout is not valid.", { message: "The layout is not valid.", errors: [{ path: "nodes[0].text", message: "Unknown field." }] });
      },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.keyboard("More.");
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save);
    await expect(await canvas.findByText("nodes[0].text: Unknown field.")).toBeInTheDocument();
  },
};

export const ASaveThatFindsTheLayoutMovedOnOffersAReload: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary()], {
      publishDraft: async () => { throw new ApiError(409, "The layout moved on.", { message: "The layout moved on.", current_version: 3 }); },
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    const loads = mocked(args.api.get).mock.calls.length;
    editor.focus();
    editor.setSelectionRange(0, 0);
    await userEvent.keyboard("Mine. ");
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save);
    await expect(await canvas.findByRole("alert")).toHaveTextContent("Someone saved version 3 while you were editing.");
    await userEvent.click(canvas.getByRole("button", { name: "Reload latest" }));
    await userEvent.click(within(await screen.findByRole("dialog", { name: "Replace your text with the latest version?" })).getByRole("button", { name: "Reload latest" }));
    await userEvent.click(await canvas.findByRole("tab", { name: "Text" }));
    await waitFor(() => expect((canvas.getByRole("textbox", { name: "Layout text" }) as HTMLTextAreaElement).value).toBe(LAYOUT_TEXT));
    await expect(mocked(args.api.get).mock.calls.length).toBe(loads + 1);
  },
};

/** The other way past a version saved meanwhile: keep the text as a draft of the new version, so saving publishes it on top. */
export const KeepMyTextRewritesTheDraftOnTheNewVersion: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    mocked(args.api.publishDraft).mockRejectedValueOnce(new ApiError(409, "The layout moved on.", { message: "The layout moved on.", current_version: 3 }));
    await typeAtEnd(editor, "Mine.");
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save);
    await userEvent.click(await canvas.findByRole("button", { name: "Keep my text on version 3" }));
    await waitFor(() => expect(args.api.writeDraft).toHaveBeenLastCalledWith("layout-1", expect.objectContaining({ base_version: 3 })));
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Keep my text on version 3" })).not.toBeInTheDocument());
  },
};

export const BlockShortcutsInsertAtTheCaretOnTheirOwnLines: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.click(canvas.getByRole("button", { name: "Insert block: Page break" }));
    await expect(editor.value).toBe(`${LAYOUT_TEXT}@page_break\n`);
    await expect(editor.selectionStart).toBe(editor.value.length);
    await expect(canvas.queryByRole("button", { name: "Insert block: Sheet" })).not.toBeInTheDocument();
  },
};

export const TheEquationShortcutInsertsAnEquationBlock: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.click(canvas.getByRole("button", { name: "Insert block: Equation" }));
    await expect(editor.value).toBe(`${LAYOUT_TEXT}@equation \\frac{a}{b} = c\n`);
  },
};

export const FieldsInsertUsingTheNameInScopeAtTheCaret: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    // The line inside the "For each requirement ... as req" block.
    await caretAtLine(editor, 6);
    await userEvent.click(canvas.getByRole("tab", { name: "Fields" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Insert {{req.status}}" }));
    await expect(editor.value.split("\n")[5]).toBe("{{req.status}}  @heading level=2 {{req.code}} {{req.title}}");
  },
};

export const WidgetsInsertOnTheirOwnLine: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.click(canvas.getByRole("tab", { name: "Widgets" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Risk Management" }));
    await userEvent.click(canvas.getByRole("button", { name: "Expand Risk register" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Headline figures" }));
    await userEvent.click(canvas.getByRole("button", { name: "Insert widget" }));
    await expect(editor.value.endsWith("[[widget.risk_management.risk-register.figures]]\n")).toBe(true);
  },
};

export const PreviewRunsTheDraftText: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    const run = canvas.getByRole("button", { name: "Run preview" });
    await waitFor(() => expect(run).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await userEvent.click(run);
    await expect(await canvas.findByTitle("Report preview")).toBeInTheDocument();
    await expect(args.api.preview).toHaveBeenCalledWith(expect.objectContaining({ text: LAYOUT_TEXT, name: "Requirements by component" }));
  },
};

export const ALayoutSharedFromElsewhereIsReadOnly: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary({ id: "layout-1", origin: "organization", editable: false, project_id: null })], {
      get: async () => ({ ...buildLayoutDetail({ origin: "organization", editable: false, project_id: null }) }),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await expect(editor).toHaveAttribute("readonly");
    await expect(canvas.getByRole("note")).toHaveTextContent("shared from the organisation, so it is read-only here");
    await expect(canvas.queryByRole("button", { name: "Save new version" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Report layout actions" }));
    await expect((await screen.findAllByRole("menuitem")).map((item) => item.textContent?.trim())).toEqual(["Duplicate…", "Export as file…"]);
  },
};

export const TheHistoryTabCanPutAnOldVersionInTheEditor: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "History" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Use this version as the new text (Version 1)" }));
    await expect(await body().findByText("Version 1 is in the editor. Save to keep it as a new version.")).toBeInTheDocument();
    await expect((await editorOf(canvasElement)).value).toBe("@layout document\n\n@heading Draft\n");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
    await expect(editor).toBeDefined();
  },
};

export const LeavingWithUnsavedChangesAsksFirst: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Report layouts" }));
    await expect(screen.queryByRole("dialog", { name: "Leave without saving?" })).not.toBeInTheDocument();
    editor.focus();
    await userEvent.keyboard("x");
    await userEvent.click(canvas.getByRole("button", { name: "Report layouts" }));
    await expect(await screen.findByRole("dialog", { name: "Leave without saving?" })).toBeInTheDocument();
  },
};

export const RenamingFromTheHeaderUpdatesTheTitle: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Edit" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Layout details" }));
    const name = dialog.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Renamed pack");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api.update).toHaveBeenCalledWith("layout-1", expect.objectContaining({ name: "Renamed pack" })));
    await expect(await canvas.findByRole("heading", { name: "Renamed pack" })).toBeInTheDocument();
  },
};

export const DeletingFromTheHeaderNeedsTheNameTyped: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Report layout actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Delete Requirements by component?" }));
    await userEvent.type(dialog.getByRole("textbox"), "Requirements by component");
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.api.remove).toHaveBeenCalledWith("layout-1"));
    await expect(await body().findByText("Layout deleted.")).toBeInTheDocument();
  },
};

export const DuplicateOpensTheDialogOnTheSavedVersion: Story = {
  args: { duplicateApi: buildDuplicateApi({ sourceName: "Requirements by component" }) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Report layout actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Duplicate…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Duplicate layout" }));
    await expect(dialog.queryByRole("note")).not.toBeInTheDocument();
    await waitFor(() => expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Requirements by component (copy)"));
    await userEvent.click(dialog.getByRole("button", { name: "Close" }));
    await expect(args.duplicateApi!.duplicate).not.toHaveBeenCalledWith(expect.objectContaining({ dry_run: false }));
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: buildLayoutApi([], { get: async () => { throw new Error("Layout not found."); } }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("Layout not found.");
  },
};

// ---- the block editor ---------------------------------------------------------------------------------------------

/** The block tree with its first heading's words taken from the text view's `@heading` line (a stand-in for the server's parser). */
function treeFromText(text: string) {
  const tree = buildOutlineTree();
  const words = /^@heading (.*)$/m.exec(text)?.[1];
  if (words !== undefined) (tree.nodes as { text?: string }[])[0].text = words;
  return tree;
}

/** An api whose saved layout is a real tree and whose text conversion mentions the first heading, so a switch is visible. */
function blocksApi() {
  const written = (tree: { nodes?: unknown }) => `@layout document\n@heading ${String((tree.nodes as { text?: string }[])[0]?.text ?? "")}\n`;
  return buildLayoutApi([buildLayoutSummary()], {
    stateful: false,
    get: fn(async () => ({ ...buildLayoutDetail(), current: { ...buildLayoutDetail().current, tree: buildOutlineTree() } })),
    parseText: fn(async (text: string) => (text.includes("BROKEN")
      ? { ok: false, tree: null, errors: [{ line: 1, column: 1, message: "Unknown word BROKEN." }] }
      : { ok: true, tree: treeFromText(text), errors: [] })),
    formatTree: fn(async (tree) => {
      if (!fakeValidate(tree).ok) throw new Error("invalid");
      return written(tree);
    }),
  });
}

const toBlocks = async (canvasElement: HTMLElement) => {
  const canvas = within(canvasElement);
  await userEvent.click(await canvas.findByRole("tab", { name: "Blocks" }));
  return canvas;
};

/** The first heading block of the block editor's workspace, once Blockly has drawn it. */
async function firstHeading(): Promise<Blockly.BlockSvg> {
  await waitFor(() => expect(Blockly.getMainWorkspace()?.getAllBlocks(false).some((b) => b.type === "rl_heading")).toBe(true));
  return (Blockly.getMainWorkspace() as Blockly.WorkspaceSvg).getAllBlocks(false).find((b) => b.type === "rl_heading") as Blockly.BlockSvg;
}

export const SwitchingToTheBlocksShowsTheLayoutAsBlocks: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await expect(await canvas.findByRole("region", { name: "Block editor" })).toBeInTheDocument();
    await expect((await firstHeading()).getFieldValue("_summary")).toBe("level 1 · Requirements of {{project_name}}");
    await expect(await canvas.findByText("No problems.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    // Nothing edited: nothing to save, and the text-only pickers are not offered.
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("textbox", { name: "Layout text" })).not.toBeInTheDocument();
  },
};
/** Selects the first heading and sets its text in the block editor beside the canvas, the only place a block's values are edited. */
async function setHeadingText(canvasElement: HTMLElement, text: string): Promise<Blockly.BlockSvg> {
  const heading = await firstHeading();
  Blockly.common.setSelected(heading);
  const box = await within(await within(canvasElement).findByTestId("block-inspector")).findByRole("textbox", { name: "Heading" });
  await userEvent.clear(box);
  if (text !== "") await userEvent.type(box, text);
  return heading;
}

export const EditingABlockSavesTheEditedTree: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = await toBlocks(canvasElement);
    await setHeadingText(canvasElement, "Edited title");
    await expect(await canvas.findByText("Unsaved changes")).toBeInTheDocument();
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save);
    await waitFor(() => expect(args.api.publishDraft).toHaveBeenCalledWith("layout-1", { draft_revision: 1, comment: "" }));
    await expect(args.api.writeDraft).toHaveBeenCalledWith(
      "layout-1",
      expect.objectContaining({ base_version: 2, tree: expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ text: "Edited title" })]) }) }),
    );
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
  },
};

export const BlocksWithProblemsCannotBeSavedAndShowThemInTheInspector: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    const heading = await setHeadingText(canvasElement, "");
    await expect(await canvas.findByText("1 problem to fix", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await waitFor(() => expect(heading.getIcon(Blockly.icons.IconType.WARNING)).toBeTruthy());
    Blockly.common.setSelected(heading);
    await expect(await canvas.findByText("Must not be empty.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await expect(await canvas.findByRole("button", { name: "Run preview" })).toBeDisabled();
  },
};

/** The Blocks view's right-hand panel has Block and Preview tabs: the block editor first, the preview a tab away. */
export const TheBlocksViewHasBlockAndPreviewTabsInOnePanel: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await firstHeading();
    const panel = canvas.getByRole("complementary", { name: "Designer tools" });
    await expect(canvasElement.querySelector(".layout-designer--blocks")).not.toBeNull();
    await expect(within(panel).getByRole("tab", { name: "Block" })).toHaveAttribute("aria-selected", "true");
    // Fields and Widgets belong to the Text view.
    await expect(within(panel).queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
    await expect(within(panel).queryByRole("button", { name: "Run preview" })).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("tab", { name: "Preview" }));
    await expect(await within(panel).findByRole("button", { name: "Run preview" })).toBeInTheDocument();
    // There is one preview, in the panel: no dialog version, and a download beside Run preview.
    await expect(within(panel).queryByRole("button", { name: "Open in dialog" })).not.toBeInTheDocument();
    await expect(within(panel).getByRole("button", { name: /Download preview/ })).toBeInTheDocument();
  },
};

/** Selecting a block brings the Block tab forward, whichever tab was showing. */
export const SelectingABlockShowsTheBlockTab: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    const heading = await firstHeading();
    const panel = canvas.getByRole("complementary", { name: "Designer tools" });
    await userEvent.click(within(panel).getByRole("tab", { name: "Preview" }));
    await expect(within(panel).getByRole("tab", { name: "Preview" })).toHaveAttribute("aria-selected", "true");
    Blockly.common.setSelected(heading);
    await waitFor(() => expect(within(panel).getByRole("tab", { name: "Block" })).toHaveAttribute("aria-selected", "true"));
    await expect(await within(panel).findByTestId("block-inspector")).toBeVisible();
  },
};

/** The panel folds to a rail and unfolds (wide layout only); the block editor survives the fold. */
export const ThePanelFoldsAndUnfoldsInBothViews: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    const hide = canvas.queryByRole("button", { name: "Hide designer panel" });
    // The toggle only exists in the wide layout; skip the interaction in a narrow viewport.
    if (!hide) return;
    await setHeadingText(canvasElement, "Kept while folded");
    await userEvent.click(hide);
    await expect(canvasElement.querySelector(".layout-designer--panel-folded")).not.toBeNull();
    await expect(canvas.queryByRole("tab", { name: "Preview" })).not.toBeInTheDocument();
    // The fold is one setting for both views.
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await expect(canvasElement.querySelector(".layout-designer--panel-folded")).not.toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Show designer panel" }));
    await expect(canvas.getByRole("tab", { name: "Fields" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("tab", { name: "Blocks" }));
    Blockly.common.setSelected(await firstHeading());
    await expect(await within(await canvas.findByTestId("block-inspector")).findByRole("textbox", { name: "Heading" })).toHaveValue("Kept while folded");
  },
};

// ---- the JSON view ------------------------------------------------------------------------------------------------

/** The outline tree with its first heading's words replaced. */
function outlineWithHeading(words: string) {
  const tree = buildOutlineTree();
  (tree.nodes as { text?: string }[])[0].text = words;
  return tree;
}

/** Replaces everything in the JSON box with `json`, as a paste would. */
async function pasteJson(canvasElement: HTMLElement, json: string) {
  const box = await within(canvasElement).findByRole("textbox", { name: "Layout JSON" });
  await userEvent.clear(box);
  await userEvent.click(box);
  await userEvent.paste(json);
}

export const ALayoutOpensOnBlocksWithBlocksTextAndJsonInThatOrder: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tabs = await canvas.findAllByRole("tab", { name: /^(Blocks|Text|JSON)$/ });
    await expect(tabs.map((tab) => tab.textContent)).toEqual(["Blocks", "Text", "JSON"]);
    await expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    await expect(canvas.queryByRole("textbox", { name: "Layout text" })).not.toBeInTheDocument();
  },
};

export const TheJsonViewShowsTheRawTreeAndOnlyANoteAboutIt: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "JSON" }));
    const box = (await canvas.findByRole("textbox", { name: "Layout JSON" })) as HTMLTextAreaElement;
    await expect(JSON.parse(box.value)).toEqual(buildOutlineTree());
    await expect(canvas.getByRole("note")).toHaveTextContent("For advanced use only.");
    // No helpers: no toolbar, snippets, side panel (Block, Preview, Fields, Widgets) or help.
    await expect(canvas.queryByRole("button", { name: "Snippets" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Preview" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Block" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
    // Save is the only action; a long tree may add the second one at the foot.
    await expect(canvas.getAllByRole("button", { name: "Save new version" })[0]).toBeInTheDocument();
    await expect(await canvas.findByText("No problems.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
  },
};

export const EditingTheJsonSavesThatTreeAndTheOtherViewsShowIt: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = await toBlocks(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "JSON" }));
    await pasteJson(canvasElement, JSON.stringify(outlineWithHeading("From the JSON")));
    await expect(await canvas.findByText("Unsaved changes")).toBeInTheDocument();
    const save = canvas.getAllByRole("button", { name: "Save new version" })[0];
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save);
    await waitFor(() => expect(args.api.publishDraft).toHaveBeenCalledWith("layout-1", { draft_revision: 1, comment: "" }));
    await expect(args.api.writeDraft).toHaveBeenCalledWith("layout-1", expect.objectContaining({ base_version: 2, tree: outlineWithHeading("From the JSON") }));
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await waitFor(async () => expect((await canvas.findByRole("textbox", { name: "Layout text" }) as HTMLTextAreaElement).value).toBe("@layout document\n@heading From the JSON\n"));
  },
};

export const JsonEditedWithoutSavingCarriesIntoTheBlocks: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "JSON" }));
    await pasteJson(canvasElement, JSON.stringify(outlineWithHeading("Carried over")));
    await waitFor(() => expect(canvas.getAllByRole("button", { name: "Save new version" })[0]).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await userEvent.click(canvas.getByRole("tab", { name: "Blocks" }));
    Blockly.common.setSelected(await firstHeading());
    await expect(await within(await canvas.findByTestId("block-inspector")).findByRole("textbox", { name: "Heading" })).toHaveValue("Carried over");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
  },
};

export const JsonThatIsNotJsonBlocksSaveAndTheSwitch: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "JSON" }));
    await pasteJson(canvasElement, "{ nope");
    await expect(await canvas.findByText("1 problem to fix")).toBeInTheDocument();
    await expect(canvas.getAllByRole("button", { name: "Save new version" })[0]).toBeDisabled();
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await expect(await canvas.findByRole("alert")).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "JSON" })).toHaveAttribute("aria-selected", "true");
  },
};

export const JsonTheServerRefusesIsListedByPathAndCannotBeSaved: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "JSON" }));
    await pasteJson(canvasElement, JSON.stringify(outlineWithHeading("")));
    await expect(await canvas.findByText("nodes[0].text: Must not be empty.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await expect(canvas.getAllByRole("button", { name: "Save new version" })[0]).toBeDisabled();
    await expect(canvas.getByText("Fix 1 problem to save")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("tab", { name: "Blocks" }));
    await expect(await canvas.findByText("Fix the problems in the JSON first; the other views need a layout that checks cleanly.")).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "JSON" })).toHaveAttribute("aria-selected", "true");
  },
};

export const ASharedLayoutsJsonIsReadOnly: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "JSON" }));
    await expect(await canvas.findByRole("textbox", { name: "Layout JSON" })).toHaveAttribute("readonly");
    await expect(canvas.queryByRole("button", { name: "Save new version" })).not.toBeInTheDocument();
  },
};

/** A check of the Blocks view still in flight when the author moves to Text must not write over what they type there. */
export const ASlowBlocksCheckDoesNotOverwriteTextTypedMeanwhile: Story = {
  args: {
    api: (() => {
      const api = blocksApi();
      api.validate = fn(async (tree) => {
        await new Promise((resolve) => setTimeout(resolve, 900));
        return fakeValidate(tree);
      });
      return api;
    })(),
  },
  play: async ({ canvasElement }) => {
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    await userEvent.keyboard("@text Typed early");
    // Wait past the slow check's answer.
    await new Promise((resolve) => setTimeout(resolve, 1600));
    await expect(editor.value).toContain("@text Typed early");
  },
};

export const SwitchingBackToTextShowsTheBlocksChanges: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await setHeadingText(canvasElement, "Renamed");
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await waitFor(async () => expect((await editorOf(canvasElement)).value).toBe("@layout document\n@heading Renamed\n"));
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
  },
};

export const SwitchingBackWithoutEditsLeavesTheTextAsTyped: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    // The original text is untouched: not re-formatted just because the blocks were opened.
    await expect((await editorOf(canvasElement)).value).toBe("@layout document\n@heading Requirements of {{project_name}}\n");
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
    // The text is checked on arrival even though it is the same text the Blocks view last wrote.
    await expect(await canvas.findByText("The text is valid.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
  },
};

export const TheBlocksAreRefusedWhileTheTextHasProblems: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(0, 0);
    await userEvent.keyboard("BROKEN ");
    await canvas.findByRole("button", { name: "Line 1, column 1: Unknown word BROKEN." }, { timeout: TEXT_CHECKED_MS });
    await userEvent.click(canvas.getByRole("tab", { name: "Blocks" }));
    await expect(await canvas.findByText("Fix the problems in the text first; the block editor needs a layout that reads cleanly.")).toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Block editor" })).not.toBeInTheDocument();
  },
};

export const BlocksWithProblemsCannotBeShownAsTextYet: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await setHeadingText(canvasElement, "");
    await expect(await canvas.findByText("1 problem to fix", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await expect(await canvas.findByText("The blocks have problems, so they cannot be shown as text yet. Fix them first.")).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "Block editor" })).toBeInTheDocument();
  },
};

export const ASharedLayoutOpensItsBlocksReadOnly: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false, parseText: async () => ({ ok: true, tree: buildOutlineTree(), errors: [] }) }) },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await expect(await canvas.findByRole("region", { name: "Block editor" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add block" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Save new version" })).not.toBeInTheDocument();
  },
};

/** Two views edit a layout: the text and the blocks. There is no separate document view. */
export const TheDesignerHasTextAndBlocksViewsOnly: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await expect(canvas.getByRole("tab", { name: "Text" })).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "Blocks" })).toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Document" })).not.toBeInTheDocument();
  },
};

// ---- snippets -----------------------------------------------------------------------------------------------------

/** Opens the snippet dialog from the Text view and chooses a snippet. */
async function chooseSnippet(canvasElement: HTMLElement, name: string) {
  await editorOf(canvasElement);
  await chooseSnippetMenuItem(canvasElement, "Insert snippet");
  const d = within(await screen.findByRole("dialog", { name: "Insert snippet" }));
  await userEvent.click(await d.findByRole("button", { name: `Select ${name}` }));
  return d;
}

export const InsertSnippetWritesItIntoTheTextAndReportsWhatChanged: Story = {
  play: async ({ canvasElement, args }) => {
    const d = await chooseSnippet(canvasElement, "Cover page");
    await expect(d.getByRole("combobox", { name: "Where to insert the snippet" })).toHaveDisplayValue("Inserting at the end of the layout");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    const editor = await editorOf(canvasElement);
    await waitFor(() => expect(editor.value).toContain("@heading {{project_name}}"));
    await expect(editor.value).toMatch(/^@layout document/);
    await expect(editor.value.trimEnd()).toMatch(/@pagebreak$/);
    // The result is a toast over the page, not a card that pushes the views down.
    await expect(await screen.findByText(/^Inserted Cover page/)).toBeInTheDocument();
    await expect(canvasElement.querySelector(".card[role=status]")).toBeNull();
    // The server applied it to the tree read from the text, at the end.
    await expect(args.api.applySnippet).toHaveBeenCalledWith(
      "cover_page", expect.objectContaining({ tree: expect.objectContaining({ family: "document" }), target: { container: "nodes", index: null } }),
    );
    await expect(within(canvasElement).getByText("Unsaved changes")).toBeInTheDocument();
  },
};

export const TheTextViewCanInsertAtTheStartInstead: Story = {
  play: async ({ canvasElement }) => {
    const d = await chooseSnippet(canvasElement, "Cover page");
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Where to insert the snippet" }), "Inserting at the start of the layout");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    const editor = await editorOf(canvasElement);
    await waitFor(() => expect(editor.value).toMatch(/^@layout document\n\n@heading \{\{project_name\}\}/));
  },
};

export const UndoPutsTheTextBackWhileItStillStands: Story = {
  play: async ({ canvasElement }) => {
    const d = await chooseSnippet(canvasElement, "Cover page");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    const editor = await editorOf(canvasElement);
    await waitFor(() => expect(editor.value).toContain("@pagebreak"));
    await userEvent.click(await screen.findByRole("button", { name: "Undo insertion" }));
    await waitFor(() => expect(editor.value).toBe(LAYOUT_TEXT));
    await waitFor(() => expect(screen.queryByText(/^Inserted Cover page/)).not.toBeInTheDocument());
  },
};

export const OnceTheTextIsEditedUndoLeavesTheTypingAlone: Story = {
  play: async ({ canvasElement }) => {
    const d = await chooseSnippet(canvasElement, "Cover page");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    const editor = await editorOf(canvasElement);
    await waitFor(() => expect(editor.value).toContain("@pagebreak"));
    await userEvent.type(editor, "x");
    const edited = editor.value;
    // Undo no longer applies once the text has changed: it must not discard the typing.
    await userEvent.click(await screen.findByRole("button", { name: "Undo insertion" }));
    await expect(editor.value).toBe(edited);
  },
};

export const TextThatDoesNotReadCleanlyIsNotAnInsertionTarget: Story = {
  play: async ({ canvasElement }) => {
    const editor = await editorOf(canvasElement);
    await userEvent.type(editor, "BROKEN");
    await chooseSnippetMenuItem(canvasElement, "Insert snippet");
    await expect(await within(canvasElement).findByText(/Fix the problems in the text before inserting a snippet/)).toBeInTheDocument();
    await expect(screen.queryByRole("dialog", { name: "Insert snippet" })).not.toBeInTheDocument();
  },
};

export const InsertSnippetInTheBlocksViewToastsTheUndoKeyAndLeavesTheNewBlockSelected: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await chooseSnippetMenuItem(canvasElement, "Insert snippet");
    const d = within(await screen.findByRole("dialog", { name: "Insert snippet" }));
    await userEvent.click(await d.findByRole("button", { name: "Select Cover page" }));
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    const toast = await screen.findByText(/^Inserted Cover page/);
    await expect(toast).toHaveTextContent("Ctrl+Z");
    // Blockly has its own undo, so the toast has no button for it.
    await expect(screen.queryByRole("button", { name: "Undo insertion" })).not.toBeInTheDocument();
    await waitFor(() => expect(Blockly.getMainWorkspace()?.getAllBlocks(false).filter((b) => b.type === "rl_page_break")).toHaveLength(1));
    // The inserted block is the selection, so the panel's Block tab is where the next edit starts.
    await waitFor(() => expect(Blockly.common.getSelected()).not.toBeNull());
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Block" })).toHaveAttribute("aria-selected", "true"));
    // Leaving the view removes the toast.
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await waitFor(() => expect(screen.queryByText(/^Inserted Cover page/)).not.toBeInTheDocument());
  },
};

export const ASharedReadOnlyLayoutOffersNoInsertSnippet: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false }) },
  play: async ({ canvasElement }) => {
    await editorOf(canvasElement);
    await expect(within(canvasElement).queryByRole("button", { name: "Snippets" })).not.toBeInTheDocument();
  },
};

// ---- save as snippet ----------------------------------------------------------------------------------------------

/** Selects lines `first` to `last` (1-based, to the end of `last`) of the editor, as a drag would. */
async function selectLines(editor: HTMLTextAreaElement, first: number, last: number) {
  const lines = editor.value.split("\n");
  const start = lines.slice(0, first - 1).join("\n").length + (first > 1 ? 1 : 0);
  const end = lines.slice(0, last).join("\n").length;
  editor.focus();
  editor.setSelectionRange(start, end);
}

export const SaveAsSnippetFromTheTextSavesTheBlockTheCaretIsIn: Story = {
  args: { snippetApi: buildSnippetStoreApi() },
  play: async ({ canvasElement, args }) => {
    const editor = await editorOf(canvasElement);
    await caretAtLine(editor, 3);
    await chooseSnippetMenuItem(canvasElement, "Save as snippet");
    const dialog = within(await screen.findByRole("dialog", { name: "Save as snippet" }));
    await expect(dialog.getByText("Saving 1 block (and everything inside it).")).toBeInTheDocument();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Title block");
    await waitFor(() => expect(dialog.getByRole("button", { name: "Save snippet" })).toBeEnabled());
    await userEvent.click(dialog.getByRole("button", { name: "Save snippet" }));
    await waitFor(() => expect(args.snippetApi?.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Title block", selection: { container: "nodes", start: 0, count: 1 } }), "project",
    ));
    await expect(await body().findByText("Saved the snippet Title block.")).toBeInTheDocument();
    await waitFor(() => expect(body().queryByRole("dialog", { name: "Save as snippet" })).not.toBeInTheDocument());
  },
};

export const SaveAsSnippetFromTheTextTakesEveryTopLevelBlockTheSelectionTouches: Story = {
  args: { snippetApi: buildSnippetStoreApi() },
  play: async ({ canvasElement, args }) => {
    const editor = await editorOf(canvasElement);
    await selectLines(editor, 3, 6);
    await chooseSnippetMenuItem(canvasElement, "Save as snippet");
    const dialog = within(await screen.findByRole("dialog", { name: "Save as snippet" }));
    await expect(dialog.getByText("Saving 2 blocks (and everything inside them).")).toBeInTheDocument();
    await waitFor(() => expect(args.snippetApi?.check).toHaveBeenCalledWith(expect.anything(), { container: "nodes", start: 0, count: 2 }, "project"));
  },
};

export const SaveAsSnippetFromTheTextNeedsTheCaretInABlock: Story = {
  args: { snippetApi: buildSnippetStoreApi() },
  play: async ({ canvasElement }) => {
    const editor = await editorOf(canvasElement);
    await caretAtLine(editor, 1);
    await chooseSnippetMenuItem(canvasElement, "Save as snippet");
    await expect(await within(canvasElement).findByText("Put the caret in a block, or select blocks, to save them as a snippet.")).toBeInTheDocument();
    await expect(screen.queryByRole("dialog", { name: "Save as snippet" })).not.toBeInTheDocument();
  },
};

export const SaveAsSnippetFromTheTextNeedsTextThatReadsCleanly: Story = {
  args: { snippetApi: buildSnippetStoreApi() },
  play: async ({ canvasElement }) => {
    const editor = await editorOf(canvasElement);
    await userEvent.type(editor, " BROKEN");
    await chooseSnippetMenuItem(canvasElement, "Save as snippet");
    await expect(await within(canvasElement).findByText(/Fix the problems in the text before saving a snippet/)).toBeInTheDocument();
    await expect(screen.queryByRole("dialog", { name: "Save as snippet" })).not.toBeInTheDocument();
  },
};

export const SaveAsSnippetInTheBlocksViewNeedsASelectedBlockAndSavesIt: Story = {
  args: { api: blocksApi(), snippetApi: buildSnippetStoreApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = await toBlocks(canvasElement);
    await expect(await snippetMenuItem(canvasElement, "Save as snippet")).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    Blockly.common.setSelected(await firstHeading());
    await canvas.findByTestId("block-inspector");
    await chooseSnippetMenuItem(canvasElement, "Save as snippet");
    const dialog = within(await screen.findByRole("dialog", { name: "Save as snippet" }));
    await expect(dialog.getByText(/Saving Heading/)).toBeInTheDocument();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Blocks heading");
    await waitFor(() => expect(dialog.getByRole("button", { name: "Save snippet" })).toBeEnabled());
    await userEvent.click(dialog.getByRole("button", { name: "Save snippet" }));
    await waitFor(() => expect(args.snippetApi?.save).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Blocks heading", selection: { container: "nodes", start: 0, count: 1 } }), "project",
    ));
  },
};

export const ASharedReadOnlyLayoutOffersNoSaveAsSnippet: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false }) },
  play: async ({ canvasElement }) => {
    await editorOf(canvasElement);
    await expect(within(canvasElement).queryByRole("button", { name: "Snippets" })).not.toBeInTheDocument();
  },
};

// ---- The shared draft: autosave, Save draft, the draft notice, conflicts and publishing.

export const AutosaveWritesTheDraftAndSaysSo: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent("No draft");
    await typeAtEnd(editor, "Closing words.");
    await waitFor(() => expect(args.api.writeDraft).toHaveBeenCalledWith(
      "layout-1", expect.objectContaining({ base_version: 2, revision: 0, tree: expect.objectContaining({ family: "document" }) }),
    ), { timeout: TEXT_CHECKED_MS });
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent(/^Draft saved/));
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
    await expect(args.api.publishDraft).not.toHaveBeenCalled();
    await expect(canvas.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  },
};

/** Looking at a layout is not editing it: opening the Text view writes no draft. */
export const OpeningTheTextViewWritesNoDraft: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await canvas.findByText("The text is valid.", undefined, { timeout: TEXT_CHECKED_MS });
    await new Promise((resolve) => setTimeout(resolve, 400));
    await expect(args.api.writeDraft).not.toHaveBeenCalled();
    await expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent("No draft");
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
  },
};

export const TextThatDoesNotReadIsNotSavedAndTheStatusSaysWhere: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(0, 0);
    await userEvent.keyboard("BROKEN ");
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent("Not saved: line 1"), { timeout: TEXT_CHECKED_MS });
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(args.api.writeDraft).not.toHaveBeenCalled();
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
  },
};

export const AFailedWriteIsReportedAndRetriedOnTheNextChange: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    mocked(args.api.writeDraft).mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const editor = await editorOf(canvasElement);
    await typeAtEnd(editor, "One.");
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent("Not saved: offline"), { timeout: TEXT_CHECKED_MS });
    // The content stays in the editor, still counted as unsaved, and the next change writes it.
    await expect(editor.value).toContain("One.");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
    await userEvent.keyboard(" Two.");
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent(/^Draft saved/), { timeout: TEXT_CHECKED_MS });
    await expect(args.api.writeDraft).toHaveBeenCalledTimes(2);
  },
};

export const WithAutosaveOffNothingIsWrittenUntilSaveDraftIsPressed: Story = {
  decorators: autosaveOff(),
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await expect(canvas.getByRole("switch", { name: "Autosave drafts" })).not.toBeChecked();
    await expect(canvas.getByRole("button", { name: "Save draft" })).toBeDisabled();
    await typeAtEnd(editor, "Trying this out.");
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent("Changes not saved to a draft"));
    await canvas.findByText("The text is valid.", undefined, { timeout: TEXT_CHECKED_MS });
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(args.api.writeDraft).not.toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Save draft" }));
    await expect(await body().findByText("Draft saved.")).toBeInTheDocument();
    await expect(args.api.writeDraft).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent(/^Draft saved/));
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
  },
};

export const DiscardChangesPutsTheEditorBack: Story = {
  decorators: autosaveOff(),
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await typeAtEnd(editor, "Unwanted.");
    await userEvent.click(await canvas.findByRole("button", { name: "Discard changes" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Discard your changes?" }));
    await expect(dialog.getByText("The editor goes back to the latest saved version.")).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Discard changes" }));
    await expect(await body().findByText("Changes discarded.")).toBeInTheDocument();
    await expect((await editorOf(canvasElement)).value).toBe(LAYOUT_TEXT);
    await expect(args.api.writeDraft).not.toHaveBeenCalled();
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
  },
};

export const TurningAutosaveOnWritesWhatIsPending: Story = {
  decorators: autosaveOff(),
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await typeAtEnd(editor, "Keep this.");
    await canvas.findByText("The text is valid.", undefined, { timeout: TEXT_CHECKED_MS });
    await expect(args.api.writeDraft).not.toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("switch", { name: "Autosave drafts" }));
    await waitFor(() => expect(args.api.writeDraft).toHaveBeenCalledTimes(1));
    await expect(canvas.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  },
};

/** With autosave on, leaving is free once the draft holds the work; with it off, unsaved edits ask first. */
export const LeavingAsksOnlyWhileChangesAreNotInTheDraft: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await typeAtEnd(editor, "Saved by autosave.");
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent(/^Draft saved/), { timeout: TEXT_CHECKED_MS });
    await userEvent.click(canvas.getByRole("button", { name: "Report layouts" }));
    await expect(screen.queryByRole("dialog", { name: "Leave without saving?" })).not.toBeInTheDocument();
  },
};

export const LeavingWithAutosaveOffAsksWhileEditsAreNotInADraft: Story = {
  decorators: autosaveOff(),
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    await typeAtEnd(editor, "Not kept.");
    await userEvent.click(canvas.getByRole("button", { name: "Report layouts" }));
    await expect(await screen.findByRole("dialog", { name: "Leave without saving?" })).toBeInTheDocument();
  },
};

const draftedApi = () => buildLayoutApi([buildLayoutSummary()], { seedDraft: buildLayoutDraft() });

export const ALayoutWithADraftOpensOnTheDraftWithANotice: Story = {
  args: { api: draftedApi(), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const notice = await canvas.findByRole("note", { name: "Draft" });
    await expect(notice).toHaveTextContent(/^Draft from Sam Rivera, .*, based on version 2\./);
    await expect((await editorOf(canvasElement)).value).toContain("@heading From the draft");
    await expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent(/^Draft saved/);
    // Opening the draft is not a change to it.
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toHaveAttribute("title", "Publishes the draft as version 3");
  },
};

export const ADraftBehindTheLatestVersionSaysSo: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary()], { stateful: false, seedDraft: buildLayoutDraft({ base_version: 1 }) }),
    autosaveDelayMs: FAST_AUTOSAVE_MS,
  },
  play: async ({ canvasElement }) => {
    const notice = await within(canvasElement).findByRole("note", { name: "Draft" });
    await expect(notice).toHaveTextContent("Version 2 was saved since this draft began.");
  },
};

export const ShowSavedVersionComparesWithoutChangingTheDraft: Story = {
  args: { api: draftedApi(), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Show saved version" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Version 2 compared with your draft" }));
    const diff = await dialog.findByLabelText("Changes from the saved version to your draft");
    await expect(diff).toHaveTextContent("+ @heading From the draft");
    await userEvent.click(dialog.getByRole("button", { name: "Close" }));
    await expect(screen.queryByRole("dialog", { name: "Version 2 compared with your draft" })).not.toBeInTheDocument();
    await expect(args.api.discardDraft).not.toHaveBeenCalled();
    await expect(canvas.getByRole("note", { name: "Draft" })).toBeInTheDocument();
  },
};

export const DiscardDraftAsksThenOpensTheLatestVersion: Story = {
  args: { api: draftedApi(), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Discard draft" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Discard this draft?" }));
    await expect(dialog.getByText(/goes back to version 2\. Published versions are not affected\./)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Discard draft" }));
    await expect(await body().findByText("Draft discarded.")).toBeInTheDocument();
    await expect(args.api.discardDraft).toHaveBeenCalledWith("layout-1");
    await waitFor(() => expect(canvas.queryByRole("note", { name: "Draft" })).not.toBeInTheDocument(), { timeout: TEXT_CHECKED_MS });
    await expect((await editorOf(canvasElement)).value).toBe(LAYOUT_TEXT);
  },
};

export const HistoryListsTheDraftAboveThePublishedVersions: Story = {
  args: { api: draftedApi(), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "History" }));
    const row = await canvas.findByRole("note", { name: "Draft" });
    await expect(row).toHaveTextContent("Sam Rivera");
    await expect(within(row).getByRole("button", { name: "Discard draft" })).toBeInTheDocument();
    await expect(await canvas.findByRole("table", { name: "Versions" })).toBeInTheDocument();
  },
};

export const PublishingTheDraftMakesOneVersionAndClearsTheNotice: Story = {
  args: { api: draftedApi(), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("note", { name: "Draft" });
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save, "Ready");
    await waitFor(() => expect(args.api.publishDraft).toHaveBeenCalledWith("layout-1", { draft_revision: 3, comment: "Ready" }));
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
    await expect(canvas.getByText("Version 3")).toBeInTheDocument();
    await waitFor(() => expect(canvas.queryByRole("note", { name: "Draft" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent("No draft");
    // The draft already held the work: publishing writes nothing first.
    await expect(args.api.writeDraft).not.toHaveBeenCalled();
    await expect(args.api.save).not.toHaveBeenCalled();
  },
};

/** Makes the next draft write find that Sam Rivera changed the draft (set inside a play: Storybook resets mocks between stories). */
const conflictOnce = (api: ReportLayoutApi) => {
  mocked(api.writeDraft).mockRejectedValueOnce(new ApiError(409, "The draft changed.", {
    message: "The draft changed.", code: "draft_conflict", draft: { base_version: 2, revision: 5, updated_by: "user-2", updated_by_name: "Sam Rivera", updated_at: "2026-11-03T09:15:00Z" },
  }));
};

export const ADraftChangedByAnotherEditorPausesAutosaveUntilYouChoose: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    conflictOnce(args.api);
    const editor = await editorOf(canvasElement);
    await typeAtEnd(editor, "Mine.");
    const banner = await canvas.findByRole("alert", { name: "Someone else changed this draft" }, { timeout: TEXT_CHECKED_MS });
    await expect(banner).toHaveTextContent("Sam Rivera changed the draft at");
    await userEvent.keyboard(" More.");
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(args.api.writeDraft).toHaveBeenCalledTimes(1);
    await userEvent.click(within(banner).getByRole("button", { name: "Keep mine" }));
    await waitFor(() => expect(args.api.writeDraft).toHaveBeenLastCalledWith(
      "layout-1", expect.objectContaining({ revision: 5, base_version: 2 }),
    ));
    await waitFor(() => expect(canvas.queryByRole("alert", { name: "Someone else changed this draft" })).not.toBeInTheDocument());
    await waitFor(() => expect(canvas.getByRole("status", { name: STATUS })).toHaveTextContent(/^Draft saved/));
  },
};

export const LoadTheirChangesReopensTheLayoutOnTheirDraft: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary()], { stateful: false }), autosaveDelayMs: FAST_AUTOSAVE_MS },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    conflictOnce(args.api);
    const editor = await editorOf(canvasElement);
    const loads = mocked(args.api.get).mock.calls.length;
    await typeAtEnd(editor, "Mine.");
    const banner = await canvas.findByRole("alert", { name: "Someone else changed this draft" }, { timeout: TEXT_CHECKED_MS });
    await userEvent.click(within(banner).getByRole("button", { name: "Load their changes" }));
    await waitFor(() => expect(mocked(args.api.get).mock.calls.length).toBe(loads + 1));
    await waitFor(() => expect(canvas.queryByRole("alert", { name: "Someone else changed this draft" })).not.toBeInTheDocument());
    await expect((await editorOf(canvasElement)).value).toBe(LAYOUT_TEXT);
  },
};

export const ASharedReadOnlyLayoutShowsNoDraftControls: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false, seedDraft: buildLayoutDraft() }) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await expect(canvas.queryByRole("status", { name: STATUS })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("switch", { name: "Autosave drafts" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("note", { name: "Draft" })).not.toBeInTheDocument();
    // A layout shared from elsewhere has no draft this scope may read, so none is fetched.
    await expect(args.api.draft).not.toHaveBeenCalled();
  },
};

/** Export as file in the actions menu opens the export dialog for this layout. */
export const ExportAsFileFromTheActionsMenu: Story = {
  args: { fileApi: buildFileApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Report layout actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Export as file…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Export 1 report as a file" }));
    await userEvent.click(dialog.getByRole("button", { name: "Export" }));
    await waitFor(() => expect(args.fileApi!.exportFile).toHaveBeenCalledWith(expect.objectContaining({ pack_ids: [] })));
  },
};
