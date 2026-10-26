import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

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
