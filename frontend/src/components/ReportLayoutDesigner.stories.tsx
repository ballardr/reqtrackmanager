import type { Meta, StoryObj } from "@storybook/react-vite";
import * as Blockly from "blockly/core";
import { expect, fn, mocked, screen, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import {
  buildLayoutApi, buildLayoutDetail, buildLayoutSummary, buildOutlineTree, fakeValidate, LAYOUT_TEXT, TEXT_CHECKED_MS,
} from "../testing/reportLayoutFixtures";
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

/** The editor once the layout has loaded. */
async function editorOf(canvasElement: HTMLElement): Promise<HTMLTextAreaElement> {
  return (await within(canvasElement).findByRole("textbox", { name: "Layout text" })) as HTMLTextAreaElement;
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
    await waitFor(() => expect(args.api.save).toHaveBeenCalledWith(
      "layout-1",
      expect.objectContaining({ base_version: 2, comment: "Added closing words", tree: expect.objectContaining({ family: "document" }) }),
    ));
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
    await expect(canvas.getByText("Version 3")).toBeInTheDocument();
  },
};

export const SavingATreeTheServerRefusesShowsItsProblems: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary()], {
      save: async () => {
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
      save: async () => { throw new ApiError(409, "The layout moved on.", { message: "The layout moved on.", current_version: 3 }); },
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
    await waitFor(() => expect((canvas.getByRole("textbox", { name: "Layout text" }) as HTMLTextAreaElement).value).toBe(LAYOUT_TEXT));
    await expect(mocked(args.api.get).mock.calls.length).toBe(loads + 1);
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
    await expect((await screen.findAllByRole("menuitem")).map((item) => item.textContent?.trim())).toEqual(["Make a copy"]);
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
  await editorOf(canvasElement);
  await userEvent.click(canvas.getByRole("tab", { name: "Blocks" }));
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
    await expect((await firstHeading()).getFieldValue("text")).toBe("Requirements of {{project_name}}");
    await expect(await canvas.findByText("No problems.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    // Nothing edited: nothing to save, and the text-only pickers are not offered.
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("textbox", { name: "Layout text" })).not.toBeInTheDocument();
  },
};

export const EditingABlockSavesTheEditedTree: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = await toBlocks(canvasElement);
    (await firstHeading()).setFieldValue("Edited title", "text");
    await expect(await canvas.findByText("Unsaved changes")).toBeInTheDocument();
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await saveVersion(save);
    await waitFor(() => expect(args.api.save).toHaveBeenCalledWith(
      "layout-1",
      expect.objectContaining({ base_version: 2, tree: expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ text: "Edited title" })]) }) }),
    ));
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
  },
};

export const BlocksWithProblemsCannotBeSavedAndShowThemInTheInspector: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    const heading = await firstHeading();
    heading.setFieldValue("", "text");
    await expect(await canvas.findByText("1 problem to fix", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await waitFor(() => expect(heading.getIcon(Blockly.icons.IconType.WARNING)).toBeTruthy());
    Blockly.common.setSelected(heading);
    await expect(await canvas.findByText("Must not be empty.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Preview" }));
    await expect(await body().findByRole("button", { name: "Run preview" })).toBeDisabled();
  },
};

export const TheBlocksViewHasTheFullWidthAndTheDialogOrPanelShowsThePreview: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    await firstHeading();
    // Closed by default: no preview beside the blocks, and the design grid is one column.
    await expect(canvas.queryByRole("button", { name: "Run preview" })).not.toBeInTheDocument();
    await expect(canvasElement.querySelector(".layout-designer--blocks")).not.toBeNull();
    // The Preview button opens it in a dialog.
    await userEvent.click(canvas.getByRole("button", { name: "Preview" }));
    const dialog = await body().findByRole("dialog", { name: "Report preview" });
    await expect(within(dialog).getByRole("button", { name: "Run preview" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(body().queryByRole("dialog", { name: "Report preview" })).not.toBeInTheDocument());
    // The panel toggle shows it beside the blocks.
    await userEvent.click(canvas.getByRole("button", { name: "Preview panel" }));
    await expect(await canvas.findByRole("button", { name: "Run preview" })).toBeInTheDocument();
    await expect(canvasElement.querySelector(".layout-designer--blocks-preview")).not.toBeNull();
  },
};

export const SwitchingBackToTextShowsTheBlocksChanges: Story = {
  args: { api: blocksApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toBlocks(canvasElement);
    (await firstHeading()).setFieldValue("Renamed", "text");
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
    (await firstHeading()).setFieldValue("", "text");
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
