import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, mocked, screen, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import {
  buildLayoutApi, buildLayoutDetail, buildLayoutSummary, buildOutlineTree, fakeValidate, LAYOUT_TEXT, TEXT_CHECKED_MS,
} from "../testing/reportLayoutFixtures";
import { withRouter } from "../testing/storybook-helpers";
import { ReportLayoutDesigner } from "./ReportLayoutDesigner";

/**
 * The report layout designer: the layout as text with its problems, a live preview, field and widget pickers that
 * insert at the caret, and the version history. Saving sends the parsed tree with the version it started from.
 */
const meta: Meta<typeof ReportLayoutDesigner> = {
  title: "Components/ReportLayoutDesigner",
  component: ReportLayoutDesigner,
  decorators: [withRouter("/projects/project-1/report-layouts/layout-1")],
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
    await userEvent.type(canvas.getByRole("textbox", { name: "Note on this change" }), "Added closing words");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await userEvent.click(save);
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
    await userEvent.click(save);
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
    await userEvent.click(save);
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
    await userEvent.click(await canvas.findByRole("button", { name: "Insert Status" }));
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

// ---- the block outline --------------------------------------------------------------------------------------------

/** The outline tree with its first heading's words taken from the text view's `@heading` line (a stand-in for the server's parser). */
function treeFromText(text: string) {
  const tree = buildOutlineTree();
  const words = /^@heading (.*)$/m.exec(text)?.[1];
  if (words !== undefined) (tree.nodes as { text?: string }[])[0].text = words;
  return tree;
}

/** An api whose saved layout is a real tree and whose text conversion mentions the first heading, so a switch is visible. */
function outlineApi() {
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

const toOutline = async (canvasElement: HTMLElement) => {
  const canvas = within(canvasElement);
  await editorOf(canvasElement);
  await userEvent.click(canvas.getByRole("tab", { name: "Outline" }));
  return canvas;
};

export const SwitchingToTheOutlineShowsTheLayoutAsBlocks: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toOutline(canvasElement);
    await expect(await canvas.findByRole("region", { name: "Layout outline" })).toBeInTheDocument();
    await expect(canvas.getAllByRole("listitem", { name: "Heading block 1" })[0]).toBeInTheDocument();
    await expect(await canvas.findByText("No problems.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    // Nothing edited: nothing to save, and the text-only pickers are not offered.
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("textbox", { name: "Layout text" })).not.toBeInTheDocument();
  },
};

export const EditingInTheOutlineSavesTheEditedTree: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = await toOutline(canvasElement);
    const heading = within(canvas.getAllByRole("listitem", { name: "Heading block 1" })[0]);
    const box = await heading.findByRole("textbox", { name: "Heading" });
    await userEvent.clear(box);
    await userEvent.type(box, "Edited title");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await userEvent.click(save);
    await waitFor(() => expect(args.api.save).toHaveBeenCalledWith(
      "layout-1",
      expect.objectContaining({ base_version: 2, tree: expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ text: "Edited title" })]) }) }),
    ));
    await expect(await body().findByText("Saved as version 3.")).toBeInTheDocument();
  },
};

export const AnOutlineWithProblemsCannotBeSavedAndShowsThemOnTheBlock: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toOutline(canvasElement);
    const heading = within(canvas.getAllByRole("listitem", { name: "Heading block 1" })[0]);
    await userEvent.clear(await heading.findByRole("textbox", { name: "Heading" }));
    await expect(await canvas.findByText("1 problem to fix", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await expect(heading.getByText("Must not be empty.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Run preview" })).toBeDisabled();
  },
};

export const SwitchingBackToTextShowsTheOutlinesChanges: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toOutline(canvasElement);
    const heading = within(canvas.getAllByRole("listitem", { name: "Heading block 1" })[0]);
    const box = await heading.findByRole("textbox", { name: "Heading" });
    await userEvent.clear(box);
    await userEvent.type(box, "Renamed");
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await expect((await editorOf(canvasElement)).value).toBe("@layout document\n@heading Renamed\n");
    await expect(canvas.getByText("Unsaved changes")).toBeInTheDocument();
  },
};

export const SwitchingBackWithoutEditsLeavesTheTextAsTyped: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toOutline(canvasElement);
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    // The original text is untouched: not re-formatted just because the outline was opened.
    await expect((await editorOf(canvasElement)).value).toBe("@layout document\n@heading Requirements of {{project_name}}\n");
    await expect(canvas.queryByText("Unsaved changes")).not.toBeInTheDocument();
  },
};

export const TheOutlineIsRefusedWhileTheTextHasProblems: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const editor = await editorOf(canvasElement);
    editor.focus();
    editor.setSelectionRange(0, 0);
    await userEvent.keyboard("BROKEN ");
    await canvas.findByRole("button", { name: "Line 1, column 1: Unknown word BROKEN." }, { timeout: TEXT_CHECKED_MS });
    await userEvent.click(canvas.getByRole("tab", { name: "Outline" }));
    await expect(await canvas.findByText("Fix the problems in the text first; the outline needs a layout that reads cleanly.")).toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Layout outline" })).not.toBeInTheDocument();
  },
};

export const AnOutlineWithProblemsCannotBeShownAsTextYet: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toOutline(canvasElement);
    const heading = within(canvas.getAllByRole("listitem", { name: "Heading block 1" })[0]);
    await userEvent.clear(await heading.findByRole("textbox", { name: "Heading" }));
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await expect(await canvas.findByText("The outline has problems, so it cannot be shown as text yet. Fix them first.")).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "Layout outline" })).toBeInTheDocument();
  },
};

export const ASharedLayoutOpensItsOutlineReadOnly: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false, parseText: async () => ({ ok: true, tree: buildOutlineTree(), errors: [] }) }) },
  play: async ({ canvasElement }) => {
    const canvas = await toOutline(canvasElement);
    await expect(await canvas.findByRole("region", { name: "Layout outline" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add block" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Save new version" })).not.toBeInTheDocument();
  },
};


// ---- the document view --------------------------------------------------------------------------------------------

const toDocument = async (canvasElement: HTMLElement) => {
  const canvas = within(canvasElement);
  await editorOf(canvasElement);
  await userEvent.click(canvas.getByRole("tab", { name: "Document" }));
  return canvas;
};

export const TheDocumentViewShowsTheLayoutAsEditableProseAndBlocks: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement }) => {
    const canvas = await toDocument(canvasElement);
    const region = within(await canvas.findByRole("region", { name: "Layout document" }));
    await expect(await region.findByText("Requirements of {{project_name}}")).toBeInTheDocument();
    await expect(region.getByText("For each record")).toBeInTheDocument();
    await expect(await canvas.findByText("No problems.", undefined, { timeout: TEXT_CHECKED_MS })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save new version" })).toBeDisabled();
    await expect(canvas.queryByRole("tab", { name: "Fields" })).not.toBeInTheDocument();
  },
};

export const AnEditInTheDocumentIsInTheOutlineAndTheTextAndSavesTheSameTree: Story = {
  args: { api: outlineApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = await toDocument(canvasElement);
    const heading = await within(await canvas.findByRole("region", { name: "Layout document" })).findByText("Requirements of {{project_name}}");
    await userEvent.click(heading);
    const selection = window.getSelection();
    selection?.selectAllChildren(heading);
    selection?.collapseToEnd();
    await new Promise((resolve) => setTimeout(resolve, 50));
    await userEvent.keyboard(" (draft)");
    await expect(await canvas.findByText("Unsaved changes")).toBeInTheDocument();
    // The outline shows the same edit: nothing converts between the two tree views.
    await userEvent.click(canvas.getByRole("tab", { name: "Outline" }));
    const first = within(canvas.getAllByRole("listitem", { name: "Heading block 1" })[0]);
    await expect(await first.findByRole("textbox", { name: "Heading" })).toHaveValue("Requirements of {{project_name}} (draft)");
    // The text view reads it too.
    await userEvent.click(canvas.getByRole("tab", { name: "Text" }));
    await waitFor(async () => expect((await editorOf(canvasElement)).value).toBe("@layout document\n@heading Requirements of {{project_name}} (draft)\n"));
    // ...and saving from the document view sends the edited tree.
    await userEvent.click(canvas.getByRole("tab", { name: "Document" }));
    const save = canvas.getByRole("button", { name: "Save new version" });
    await waitFor(() => expect(save).toBeEnabled(), { timeout: TEXT_CHECKED_MS });
    await userEvent.click(save);
    await waitFor(() => expect(args.api.save).toHaveBeenCalledWith(
      "layout-1",
      expect.objectContaining({ tree: expect.objectContaining({ nodes: expect.arrayContaining([expect.objectContaining({ text: "Requirements of {{project_name}} (draft)" })]) }) }),
    ));
  },
};

export const ATableLayoutHasNoDocumentView: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary({ family: "table" })], {
      stateful: false, parseText: async () => ({ ok: true, tree: { schema_version: 1, family: "table", nodes: [] }, errors: [] }),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await editorOf(canvasElement);
    await expect(canvas.getByRole("tab", { name: "Outline" })).toBeInTheDocument();
    await expect(canvas.queryByRole("tab", { name: "Document" })).not.toBeInTheDocument();
  },
};

export const ALayoutTheDocumentCannotShowIsRefusedWithTheReason: Story = {
  args: {
    api: buildLayoutApi([buildLayoutSummary()], {
      stateful: false,
      parseText: async () => ({
        ok: true, errors: [], tree: { schema_version: 1, family: "document", nodes: [{ type: "each", source: { record_type: "requirement" }, children: "nope" }] },
      }),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = await toDocument(canvasElement);
    await expect(await canvas.findByText(/The document view cannot show this layout without changing it: nodes\[0\]\.children/)).toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Layout document" })).not.toBeInTheDocument();
    // The text view is where it still is, and the outline can still open it.
    await userEvent.click(canvas.getByRole("tab", { name: "Outline" }));
    await expect(await canvas.findByRole("region", { name: "Layout outline" })).toBeInTheDocument();
  },
};

export const ASharedLayoutOpensItsDocumentReadOnly: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ editable: false, origin: "organization" })], { stateful: false, parseText: async () => ({ ok: true, tree: buildOutlineTree(), errors: [] }) }) },
  play: async ({ canvasElement }) => {
    const canvas = await toDocument(canvasElement);
    const region = within(await canvas.findByRole("region", { name: "Layout document" }));
    await region.findByText("Requirements of {{project_name}}");
    await expect(region.queryByRole("button", { name: "Add block" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Save new version" })).not.toBeInTheDocument();
  },
};
