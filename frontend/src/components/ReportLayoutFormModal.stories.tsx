import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api as http } from "../api/client";

import { buildLayoutApi, buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportLayoutFormModal } from "./ReportLayoutFormModal";

/** The dialog that creates a report layout or edits its name and description. */
const meta: Meta<typeof ReportLayoutFormModal> = {
  title: "Components/ReportLayoutFormModal",
  component: ReportLayoutFormModal,
  args: { api: buildLayoutApi([]), onClose: fn(), onSaved: fn() },
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

/** The folder is optional (so unmarked), suggests the folders the scope already uses and is saved tidied. */
export const FolderSuggestsExistingFoldersAndIsSavedTidied: Story = {
  args: { api: buildLayoutApi([buildLayoutSummary({ folder: "Handover/Quarterly" })]) },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name", "Kind of report"]);
    await waitFor(() => expect(document.querySelectorAll("datalist option").length).toBe(2)); // Handover and Handover/Quarterly
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Filed");
    await userEvent.type(dialog.getByRole("combobox", { name: "Folder" }), " Handover / Annual ");
    await userEvent.click(dialog.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(args.api.create).toHaveBeenCalledWith(expect.objectContaining({ name: "Filed", folder: "Handover/Annual" })));
  },
};

/** A path the server would refuse is flagged and cannot be saved. */
export const AFolderThatIsTooDeepCannotBeSaved: Story = {
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New report layout" }));
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Deep");
    await userEvent.type(dialog.getByRole("combobox", { name: "Folder" }), "a/b/c/d");
    await expect(dialog.getByRole("alert")).toHaveTextContent("at most 3 levels");
    await expect(dialog.getByRole("button", { name: "Create" })).toBeDisabled();
  },
};

/** Editing starts from the layout's folder and sends the change. */
export const EditingChangesTheFolder: Story = {
  args: { layout: buildLayoutSummary({ folder: "Old" }) },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "Layout details" }));
    const folder = dialog.getByRole("combobox", { name: "Folder" });
    await expect(folder).toHaveValue("Old");
    await userEvent.clear(folder);
    await userEvent.type(folder, "New/Sub");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api.update).toHaveBeenCalledWith("layout-1", expect.objectContaining({ folder: "New/Sub" })));
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
