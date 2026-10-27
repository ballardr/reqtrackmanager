import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildCategoriesVariable } from "../testing/reportPackFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportPackSetFormModal } from "./ReportPackSetFormModal";

/** The dialog that edits a saved set, or one project's override of a shared set. */
const meta: Meta<typeof ReportPackSetFormModal> = {
  title: "Components/Reports/ReportPackSetFormModal",
  component: ReportPackSetFormModal,
  args: { variables: [buildCategoriesVariable()], onClose: fn(), onSave: fn(async () => undefined) },
};
export default meta;

type Story = StoryObj<typeof ReportPackSetFormModal>;

export const ANewSetNeedsAName: Story = {
  args: { title: "New saved set", initialName: "", initialValues: {} },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: "New saved set" }));
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Team Alpha");
    await userEvent.click(dialog.getByRole("button", { name: /Choose one or more|Categories/ }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Security" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith("Team Alpha", { categories: ["Security"] }));
  },
};

export const AnOverrideKeepsOnlyWhatDiffersFromTheSharedSet: Story = {
  args: {
    title: "Override Team Alpha for this project", hint: "Change only what this project needs; the rest keeps following the shared set.",
    initialName: null, initialValues: { categories: ["Security"] }, sharedValues: { categories: ["Security"] },
  },
  play: async ({ args }) => {
    const dialog = within(await screen.findByRole("dialog", { name: /Override Team Alpha/ }));
    await expect(dialog.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith("", {}));
  },
};

export const ARefusalIsShownInTheDialog: Story = {
  args: {
    title: "New saved set", initialName: "Taken", initialValues: {},
    onSave: async () => { throw new Error('A set called "Taken" already exists for this pack.'); },
  },
  play: async () => {
    const dialog = within(await screen.findByRole("dialog", { name: "New saved set" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await dialog.findByText(/already exists for this pack/)).toBeInTheDocument();
  },
};

export const NoVariablesSaysSo: Story = {
  args: { title: "New saved set", initialName: "", initialValues: {}, variables: [] },
  play: async () => {
    await expect(await within(await screen.findByRole("dialog")).findByText("Add variables to the pack first.")).toBeInTheDocument();
  },
};
