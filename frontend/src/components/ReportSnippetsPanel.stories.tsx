import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildSavedSnippets, buildSnippetStoreApi } from "../testing/reportSnippetStoreFixtures";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportSnippetsPanel } from "./ReportSnippetsPanel";

/**
 * The Report snippets section of Report setup: the snippets saved from the designer, with where each comes from, its blocks and
 * what it carries. A project hides an inherited snippet (and restores it); an owner renames or deletes its own; a copy goes to the
 * scope or up to the organisation.
 */
const meta: Meta<typeof ReportSnippetsPanel> = {
  title: "Components/Reports/ReportSnippetsPanel",
  component: ReportSnippetsPanel,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: { api: buildSnippetStoreApi() },
  // Each replay builds its own fake so a hide or a delete never changes what the next story reads.
  render: (args) => <ReportSnippetsPanel {...args} api={args.api ?? buildSnippetStoreApi()} />,
};
export default meta;

type Story = StoryObj<typeof ReportSnippetsPanel>;

const table = async (canvasElement: HTMLElement) => within(await within(canvasElement).findByRole("table", { name: "Saved snippets" }));
const menuOf = async (name: string) => {
  await userEvent.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
  return within(await screen.findByRole("menu"));
};

export const ListsTheSnippetsWithTheirSourceBlocksAndWhatTheyCarry: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ canvasElement }) => {
    const t = await table(canvasElement);
    const rows = t.getAllByRole("row").slice(1);
    await expect(rows).toHaveLength(3);
    await expect(rows[0]).toHaveTextContent("House risk table");
    await expect(rows[0]).toHaveTextContent("This project");
    await expect(rows[1]).toHaveTextContent("The organisation");
    await expect(rows[1]).toHaveTextContent("style Wide");
    await expect(rows[2]).toHaveTextContent("A parent project");
    await expect(rows[2]).toHaveTextContent("Hidden here");
    await expect(rows[2]).toHaveTextContent("variable audience");
  },
};

export const SearchNarrowsTheList: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await table(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "Search saved snippets" }), "approval");
    const t = await table(canvasElement);
    await expect(t.getAllByRole("row").slice(1)).toHaveLength(1);
    await userEvent.clear(canvas.getByRole("textbox", { name: "Search saved snippets" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Search saved snippets" }), "zzz");
    await expect(await canvas.findByText("No saved snippet matches.")).toBeInTheDocument();
  },
};

export const AnEmptyListSaysHowToSaveOne: Story = {
  args: { api: buildSnippetStoreApi([]) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/No snippets saved yet/)).toBeInTheDocument();
  },
};

export const AnOwnSnippetCanBeEditedCopiedAndDeletedButNotHidden: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ canvasElement }) => {
    await table(canvasElement);
    const menu = await menuOf("House risk table");
    await expect(menu.getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual([
      "Edit details", "Make a copy", "Copy to the organisation", "Delete",
    ]);
  },
};

export const AnInheritedSnippetCanBeCopiedAndHiddenButNotChanged: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ canvasElement }) => {
    await table(canvasElement);
    const menu = await menuOf("Approval footer");
    await expect(menu.getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual([
      "Make a copy", "Copy to the organisation", "Hide in this project",
    ]);
  },
};

export const HidingAnInheritedSnippetAsksFirstThenFlagsIt: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ args, canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("Approval footer")).findByRole("menuitem", { name: "Hide in this project" }));
    const confirm = within(await screen.findByRole("dialog"));
    await expect(confirm.getByText(/no longer offered when inserting a snippet in this project/)).toBeInTheDocument();
    await userEvent.click(confirm.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(args.api?.setHidden).toHaveBeenCalledWith("snippet-2", true));
    await waitFor(async () => expect((await table(canvasElement)).getAllByRole("row")[2]).toHaveTextContent("Hidden here"));
  },
};

export const AddOrganisationDefaultsRestoresTheHiddenOnes: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ args, canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await within(canvasElement).findByRole("button", { name: /Add organisation defaults/ }));
    const dialog = within(await screen.findByRole("dialog"));
    await expect(dialog.getByText("Audience note")).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: /Add|Restore|Show/ }));
    await waitFor(() => expect(args.api?.restore).toHaveBeenCalledWith(["snippet-3"]));
  },
};

export const ASnippetHiddenHereCanBeShownAgainFromItsMenu: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ args, canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("Audience note")).findByRole("menuitem", { name: "Show in this project" }));
    await waitFor(() => expect(args.api?.setHidden).toHaveBeenCalledWith("snippet-3", false));
  },
};

export const DeletingAnOwnSnippetNeedsItsNameTyped: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ args, canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("House risk table")).findByRole("menuitem", { name: "Delete" }));
    const confirm = within(await screen.findByRole("dialog"));
    await expect(confirm.getByText(/Layouts already built from it keep their blocks/)).toBeInTheDocument();
    const go = confirm.getByRole("button", { name: "Delete" });
    await expect(go).toBeDisabled();
    await userEvent.type(confirm.getByRole("textbox"), "House risk table");
    await userEvent.click(go);
    await waitFor(() => expect(args.api?.remove).toHaveBeenCalledWith("snippet-1"));
    await waitFor(async () => expect((await table(canvasElement)).getAllByRole("row").slice(1)).toHaveLength(2));
  },
};

export const EditingChangesTheDetailsThroughTheSameFieldsAsSaving: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ args, canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("House risk table")).findByRole("menuitem", { name: "Edit details" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Edit House risk table" }));
    const name = dialog.getByRole("textbox", { name: "Name" });
    await expect(name).toHaveValue("House risk table");
    await userEvent.clear(name);
    await userEvent.type(name, "Risk table");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api?.update).toHaveBeenCalledWith("snippet-1", { name: "Risk table", description: "Heading and a table of risks in the house style.", category: "House style" }));
    await expect(await within(canvasElement).findByText("Risk table")).toBeInTheDocument();
  },
};

export const ATakenNameWhenEditingIsReportedInTheDialog: Story = {
  args: { api: buildSnippetStoreApi(undefined, { taken: ["approval footer"] }) },
  play: async ({ canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("House risk table")).findByRole("menuitem", { name: "Edit details" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Edit House risk table" }));
    const name = dialog.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Approval footer");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await dialog.findByText("A saved snippet with this name already exists here.")).toBeInTheDocument();
  },
};

export const CopyingUpWithAProjectPictureIsRefusedAndNamed: Story = {
  args: { api: buildSnippetStoreApi(undefined, { copyUpRefused: ["snippet-1"] }) },
  play: async ({ canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("House risk table")).findByRole("menuitem", { name: "Copy to the organisation" }));
    const alert = await within(canvasElement).findByRole("alert");
    await expect(alert).toHaveTextContent("cannot be shared with the whole organisation");
    await expect(alert).toHaveTextContent("site-logo.png");
  },
};

export const MakingACopyAddsItToTheList: Story = {
  args: { api: buildSnippetStoreApi() },
  play: async ({ args, canvasElement }) => {
    await table(canvasElement);
    await userEvent.click(await (await menuOf("House risk table")).findByRole("menuitem", { name: "Make a copy" }));
    await waitFor(() => expect(args.api?.copy).toHaveBeenCalledWith("snippet-1", { target: "project" }));
    await expect(await within(canvasElement).findByText("House risk table (copy)")).toBeInTheDocument();
  },
};

export const AnOrganisationListHasNoHideOrCopyUp: Story = {
  args: {
    api: buildSnippetStoreApi(
      buildSavedSnippets().filter((s) => s.origin === "organization").map((s) => ({ ...s, editable: true })),
      { scope: { kind: "organization", id: "org-1" } },
    ),
  },
  play: async ({ canvasElement }) => {
    await table(canvasElement);
    const menu = await menuOf("Approval footer");
    await expect(menu.getAllByRole("menuitem").map((i) => i.textContent?.trim())).toEqual(["Edit details", "Make a copy", "Delete"]);
    await expect(within(canvasElement).queryByRole("button", { name: /Add organisation defaults/ })).not.toBeInTheDocument();
  },
};

export const ALoadFailureIsShown: Story = {
  args: { api: { ...buildSnippetStoreApi(), list: fn(async () => { throw new Error("nope"); }) } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The saved snippets could not be loaded.");
  },
};
