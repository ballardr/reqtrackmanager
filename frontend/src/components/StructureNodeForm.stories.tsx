import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildStructureApi, buildStructureTree, STRUCTURE_PROJECT_ID } from "../testing/structureFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { StructureNodeForm } from "./StructureNodeForm";

const [hardware] = buildStructureTree().components;
const [cooling] = buildStructureTree().categories;

/**
 * The create and edit form of a component or category, in a side panel with Save in its header. Create and edit share
 * one field group; the prefix is suggested from the name on create only.
 */
const meta: Meta<typeof StructureNodeForm> = {
  title: "Components/StructureNodeForm",
  component: StructureNodeForm,
  args: { projectId: STRUCTURE_PROJECT_ID, onSaved: fn(), onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof StructureNodeForm>;

export const CreateComponent: Story = {
  args: { api: buildStructureApi(), target: { kind: "component" } },
  play: async () => {
    const dialog = await screen.findByRole("dialog", { name: "Add component" });
    await expect(requiredCaptions(dialog)).toEqual(["Name", "Prefix"]);
    await expect(within(dialog).getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

export const CreateCategoryNamesItsComponent: Story = {
  args: { api: buildStructureApi(), target: { kind: "category", component: hardware } },
  play: async () => {
    await expect(await screen.findByRole("dialog", { name: "Add category to Hardware" })).toBeInTheDocument();
  },
};

export const SavingCreatesAndCloses: Story = {
  args: { api: buildStructureApi(), target: { kind: "category", component: hardware } },
  play: async ({ args }) => {
    const panel = within(await screen.findByRole("dialog", { name: "Add category to Hardware" }));
    await userEvent.type(panel.getByRole("textbox", { name: "Name" }), "Wiring");
    await waitFor(() => expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("WIRING"));
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.createCategory).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "c-hw", { name: "Wiring", prefix: "WIRING" }));
    await waitFor(() => expect(args.onSaved).toHaveBeenCalled());
    await expect(args.onClose).toHaveBeenCalled();
  },
};

export const EditShowsTheStoredValues: Story = {
  args: { api: buildStructureApi(), target: { kind: "category", component: hardware, node: cooling } },
  play: async () => {
    const panel = within(await screen.findByRole("dialog", { name: "Edit category Cooling" }));
    await expect(panel.getByRole("textbox", { name: "Name" })).toHaveValue("Cooling");
    await expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("COOL");
  },
};

/** The server's refusal is shown and the panel stays open. */
export const ARefusalStaysInThePanel: Story = {
  args: { api: buildStructureApi(), target: { kind: "category", component: hardware } },
  play: async ({ args }) => {
    const panel = within(await screen.findByRole("dialog", { name: "Add category to Hardware" }));
    await userEvent.type(panel.getByRole("textbox", { name: "Name" }), "Another");
    const prefix = panel.getByRole("textbox", { name: "Prefix" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "COOL");
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
    await expect(await screen.findByText("A category with this prefix already exists under this component.")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};
