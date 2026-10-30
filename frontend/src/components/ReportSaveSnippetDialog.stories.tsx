import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import type { ReportLayoutTree } from "../api/reportLayouts";
import type { SnippetCheck } from "../api/reportSnippets";
import { buildSnippetStoreApi } from "../testing/reportSnippetStoreFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportSaveSnippetDialog } from "./ReportSaveSnippetDialog";

const TREE: ReportLayoutTree = {
  schema_version: 1, family: "document", nodes: [{ type: "heading", text: "House risk table", level: 2 }, { type: "text", text: "Body" }],
};
const PICTURE_TREE: ReportLayoutTree = { ...TREE, nodes: [{ type: "image", file: "file-1", alt: "Logo" }] };
const SELECTION = { container: "nodes", start: 0, count: 1 };

/**
 * Save as snippet: the name (required), description and category of a selection of the layout, where to keep it (a project can
 * also keep it for the organisation), and what the server says saving it would store: how many blocks, the page styles and
 * variables carried, or why the selection cannot be saved.
 */
const meta: Meta<typeof ReportSaveSnippetDialog> = {
  title: "Components/Reports/ReportSaveSnippetDialog",
  component: ReportSaveSnippetDialog,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: {
    api: buildSnippetStoreApi(), tree: TREE, selection: SELECTION, selectionLabel: "Saving 1 block (and everything inside it).",
    onClose: fn(), onSaved: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ReportSaveSnippetDialog>;

const dialog = async () => within(await screen.findByRole("dialog", { name: "Save as snippet" }));

export const SavesTheSelectionWithItsNameDescriptionAndCategory: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await expect(d.getByRole("button", { name: "Save snippet" })).toBeDisabled();
    await expect(await d.findByText("Saves 1 block.")).toBeInTheDocument();
    await userEvent.type(d.getByRole("textbox", { name: "Name" }), "House risk table");
    await userEvent.type(d.getByRole("textbox", { name: "Description" }), "A heading");
    await userEvent.type(d.getByRole("combobox", { name: "Category" }), "House style");
    await userEvent.click(d.getByRole("button", { name: "Save snippet" }));
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
    await expect(args.api.save).toHaveBeenCalledWith(
      { name: "House risk table", description: "A heading", category: "House style", tree: TREE, selection: SELECTION }, "project",
    );
  },
};

export const SaveStaysOffUntilTheServerHasChecked: Story = {
  args: { api: { ...buildSnippetStoreApi(), check: fn(() => new Promise<SnippetCheck>(() => undefined)) } },
  play: async () => {
    const d = await dialog();
    await userEvent.type(d.getByRole("textbox", { name: "Name" }), "Pending");
    await expect(d.getByRole("button", { name: "Save snippet" })).toBeDisabled();
  },
};

export const ListsThePageStylesAndVariablesTheSnippetCarries: Story = {
  args: { api: buildSnippetStoreApi(undefined, { carries: { page_styles: ["Wide"], variables: ["audience"] } }) },
  play: async () => {
    const d = await dialog();
    await expect(await d.findByText("Also carries the page styles: Wide.")).toBeInTheDocument();
    await expect(d.getByText("Also carries the variables: audience.")).toBeInTheDocument();
  },
};

export const OffersTheCategoriesAlreadyInUse: Story = {
  play: async () => {
    await dialog();
    await waitFor(() => expect(document.querySelectorAll("datalist option").length).toBe(2));
    await expect([...document.querySelectorAll("datalist option")].map((o) => (o as HTMLOptionElement).value)).toEqual(["House style", "Notes"]);
  },
};

export const KeepingItForTheOrganisationWithAProjectPictureIsRefusedAndNamed: Story = {
  args: { tree: PICTURE_TREE },
  play: async ({ args }) => {
    const d = await dialog();
    await expect(await d.findByText("Saves 1 block.")).toBeInTheDocument();
    await userEvent.type(d.getByRole("textbox", { name: "Name" }), "Logo block");
    await userEvent.selectOptions(d.getByRole("combobox", { name: /Keep it for/ }), "organization");
    const reason = await d.findByRole("alert");
    await expect(reason).toHaveTextContent("This selection cannot be saved as it is:");
    await expect(reason).toHaveTextContent("site-logo.png");
    await expect(d.getByRole("button", { name: "Save snippet" })).toBeDisabled();
    await expect(args.api.check).toHaveBeenLastCalledWith(PICTURE_TREE, SELECTION, "organization");
  },
};

export const ATakenNameIsReportedInTheHeader: Story = {
  args: { api: buildSnippetStoreApi(undefined, { taken: ["house risk table"] }) },
  play: async ({ args }) => {
    const d = await dialog();
    await expect(await d.findByText("Saves 1 block.")).toBeInTheDocument();
    await userEvent.type(d.getByRole("textbox", { name: "Name" }), "House risk table");
    await userEvent.click(d.getByRole("button", { name: "Save snippet" }));
    await expect(await d.findByText("A saved snippet with this name already exists here.")).toBeInTheDocument();
    await expect(args.onSaved).not.toHaveBeenCalled();
  },
};

export const AnOrganisationScopeHasNoLevelChoice: Story = {
  args: { api: buildSnippetStoreApi(undefined, { scope: { kind: "organization", id: "org-1" } }) },
  play: async () => {
    const d = await dialog();
    await expect(await d.findByText("Saves 1 block.")).toBeInTheDocument();
    await expect(d.queryByRole("combobox", { name: /Keep it for/ })).not.toBeInTheDocument();
  },
};

export const CancelClosesWithoutSaving: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Cancel" }));
    await expect(args.onClose).toHaveBeenCalled();
    await expect(args.api.save).not.toHaveBeenCalled();
  },
};
