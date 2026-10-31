import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { buildLayoutApi } from "../testing/reportLayoutFixtures";
import { buildSavedSnippet, buildSnippetStoreApi } from "../testing/reportSnippetStoreFixtures";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportSnippetEditorDialog } from "./ReportSnippetEditorDialog";

/**
 * The dialog that makes a saved snippet from nothing, or edits one: the details and the blocks, in the Blocks and Text editors a
 * layout is written in. The server's check says what saving would store before Save is available.
 */
const meta: Meta<typeof ReportSnippetEditorDialog> = {
  title: "Components/Reports/ReportSnippetEditorDialog",
  component: ReportSnippetEditorDialog,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: {
    api: buildSnippetStoreApi(), layoutApi: buildLayoutApi([], { stateful: false }), categories: ["House style"], onClose: fn(), onSaved: fn(),
  },
  // Each replay builds its own fakes so a save in one never changes what the next reads.
  render: (args) => <ReportSnippetEditorDialog {...args} api={buildSnippetStoreApi()} layoutApi={buildLayoutApi([], { stateful: false })} />,
};
export default meta;

type Story = StoryObj<typeof ReportSnippetEditorDialog>;

const dialogOf = async (name: string) => within(await screen.findByRole("dialog", { name }));

export const CreatingStartsEmptyAndAsksForTheKindFirst: Story = {
  play: async () => {
    const dialog = await dialogOf("New snippet");
    await expect(await dialog.findByRole("combobox", { name: /Kind/ })).toHaveValue("document");
    await expect(dialog.getByRole("tab", { name: "Blocks" })).toHaveAttribute("aria-selected", "true");
    await expect(await dialog.findByText("Add at least one block to save the snippet.")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Save snippet" })).toBeDisabled();
    await expect(requiredCaptions(document.body)).toEqual(["Kind", "Name"]);
  },
};

export const ChoosingTableMakesTheSnippetATableOne: Story = {
  play: async () => {
    const dialog = await dialogOf("New snippet");
    await userEvent.selectOptions(await dialog.findByRole("combobox", { name: /Kind/ }), "table");
    await expect(dialog.getByRole("combobox", { name: /Kind/ })).toHaveValue("table");
  },
};

export const TheTextViewShowsTheSnippetAsLayoutText: Story = {
  play: async () => {
    const dialog = await dialogOf("New snippet");
    await userEvent.click(await dialog.findByRole("tab", { name: "Text" }));
    await expect(await dialog.findByRole("textbox", { name: "Snippet text" })).toHaveValue("@layout document\n");
  },
};

export const EditingLoadsTheSnippetsBlocksAndSavesThemAgain: Story = {
  args: { snippet: buildSavedSnippet() },
  render: (args) => {
    const api = buildSnippetStoreApi();
    return <ReportSnippetEditorDialog {...args} api={api} layoutApi={buildLayoutApi([], { stateful: false })} />;
  },
  play: async ({ args }) => {
    const dialog = await dialogOf("Edit House risk table");
    await expect(dialog.getByRole("textbox", { name: /Name/ })).toHaveValue("House risk table");
    await expect(dialog.queryByRole("combobox", { name: /Kind/ })).not.toBeInTheDocument();
    const save = dialog.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
  },
};

export const ATakenNameIsReportedInTheDialog: Story = {
  args: { snippet: buildSavedSnippet() },
  render: (args) => (
    <ReportSnippetEditorDialog
      {...args} api={buildSnippetStoreApi(undefined, { taken: ["approval footer"] })} layoutApi={buildLayoutApi([], { stateful: false })}
    />
  ),
  play: async () => {
    const dialog = await dialogOf("Edit House risk table");
    const name = dialog.getByRole("textbox", { name: /Name/ });
    await userEvent.clear(name);
    await userEvent.type(name, "Approval footer");
    const save = dialog.getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await expect(await dialog.findByText("A saved snippet with this name already exists here.")).toBeInTheDocument();
  },
};

export const ALoadFailureIsShown: Story = {
  render: (args) => (
    <ReportSnippetEditorDialog
      {...args} api={buildSnippetStoreApi()}
      layoutApi={buildLayoutApi([], { stateful: false, fields: fn(async () => { throw new Error("nope"); }) })}
    />
  ),
  play: async () => {
    const dialog = await dialogOf("New snippet");
    await expect(await dialog.findByRole("alert")).toHaveTextContent("The editor could not be loaded.");
  },
};
