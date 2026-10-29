import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api as http } from "../api/client";

import { buildFolderApi } from "../testing/reportFolderFixtures";
import { buildLayoutApi, buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";

/** The dialog that creates a report layout or edits its name and description. */
const meta: Meta<typeof ReportLayoutFormModal> = {
  title: "Components/ReportLayoutFormModal",
  component: ReportLayoutFormModal,
  args: { api: buildLayoutApi([]), folderApi: buildFolderApi(), onClose: fn(), onSaved: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutFormModal>;

/** Creating marks the name and the kind required; the kind is chosen now because it cannot change later. */
export const CreatingAsksForANameAndAKind: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name", "Kind of report"]);
    await expect(dialog.getByRole("combobox", { name: "Kind of report" })).toHaveValue("document");
    await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
  },
};

/** The server writes the empty tree of a family, so the dialog asks it rather than spelling the tree out. */
export const CreatingStartsFromTheServersEmptyLayoutOfThatKind: Story = {
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Sheets");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Kind of report" }), "table");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api.parseText).toHaveBeenCalledWith("@layout table\n"));
    await waitFor(() => expect(args.api.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Sheets", family: "table" })));
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
    await expect(args.onClose).toHaveBeenCalled();
  },
};

/** Editing offers the same name and description but not the kind, and only the name is required. */
export const EditingOffersNoKind: Story = {
  args: { layout: buildLayoutSummary() },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Layout details" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await expect(dialog.queryByRole("combobox", { name: "Kind of report" })).not.toBeInTheDocument();
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Requirements by component");
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await expect(args.onClose).toHaveBeenCalled();
  },
};

/** The folder is optional (so unmarked), chosen from the scope's folders and saved with the layout. */
export const FolderIsChosenFromTheTreeAndSaved: Story = {
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name", "Kind of report"]);
    await expect(await dialog.findByRole("radio", { name: "No folder (the default)" })).toBeChecked();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Filed");
    await userEvent.click(await dialog.findByRole("radio", { name: "Quarterly" }));
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Filed", folder: "Handover/Quarterly" })));
  },
};

/** A folder added in the dialog is chosen at once and saved with the layout; the page behind is told to reload. */
export const AFolderAddedHereIsSavedWithTheLayout: Story = {
  args: { onFoldersChanged: fn() },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Fresh");
    await userEvent.click(await dialog.findByRole("button", { name: "New folder" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name of the new folder" }), "Annual");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.onFoldersChanged).toHaveBeenCalled());
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Fresh", folder: "Annual" })));
  },
};

/** Save stays disabled while a folder change is in flight, so the layout cannot be saved before the chosen folder has followed it. */
const slowFolders = (() => {
  const folderApi = buildFolderApi();
  const add = folderApi.add;
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  folderApi.add = fn(async (path: string) => { await gate; return add(path); });
  return { folderApi, release: () => release() };
})();

export const SaveWaitsForAFolderChangeToFinish: Story = {
  args: { folderApi: slowFolders.folderApi },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Waiting");
    await expect(dialog.getByRole("button", { name: "Create" })).toBeEnabled();
    await userEvent.click(await dialog.findByRole("button", { name: "New folder" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name of the new folder" }), "Slow");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled());
    slowFolders.release();
    await expect(await dialog.findByRole("radio", { name: "Slow" })).toBeChecked();
    await waitFor(() => expect(dialog.getByRole("button", { name: "Create" })).toBeEnabled());
  },
};

/** Editing starts from the layout's folder and sends the change. */
export const EditingChangesTheFolder: Story = {
  args: { layout: buildLayoutSummary({ folder: "Shared" }) },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Layout details" }));
    await expect(await dialog.findByRole("radio", { name: "Shared" })).toBeChecked();
    await userEvent.click(dialog.getByRole("radio", { name: "Handover" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api.update).toHaveBeenCalledWith("layout-1", expect.objectContaining({ folder: "Handover" })));
  },
};

/** Editing offers the layout's own branding template (the organisation's default until one is chosen); creating does not. */
export const EditingOffersTheLayoutsOwnTemplate: Story = {
  args: { layout: buildLayoutSummary() },
  beforeEach: () => {
    spyOn(http, "get").mockImplementation(async (path: string) => {
      if (path.includes("/report-templates")) {
        return [{
          id: "tpl-1", organization_id: "org-1", name: "Corporate", accent_color_hex: "#475569", include_cover_page: true,
          include_logo: true, footer_text: null, chapters_per_component: true, is_default: true,
        }];
      }
      return [];
    });
  },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Layout details" }));
    const select = await dialog.findByRole("combobox", { name: "Branding template" });
    await expect(select).toHaveValue("");
    await userEvent.selectOptions(select, "tpl-1");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api.update).toHaveBeenCalledWith("layout-1", expect.objectContaining({ report_template_id: "tpl-1" })));
  },
};

/** Creating a layout does not ask for a template: the organisation's default applies until the layout is edited. */
export const CreatingOffersNoTemplate: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await expect(dialog.queryByRole("combobox", { name: "Branding template" })).not.toBeInTheDocument();
  },
};
