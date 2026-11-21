import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildStructureApi, STRUCTURE_PROJECT_ID } from "../testing/structureFixtures";
import { InlineStructureForm } from "./InlineStructureForm";

/**
 * The small form inside a create dialog that adds the first component, or the first category under a component, for a
 * project that has none: the Structure page's name and prefix fields with an Add button.
 */
const meta: Meta<typeof InlineStructureForm> = {
  title: "Components/InlineStructureForm",
  component: InlineStructureForm,
  args: { projectId: STRUCTURE_PROJECT_ID, onCreated: fn() },
};
export default meta;

type Story = StoryObj<typeof InlineStructureForm>;

export const AddsTheFirstComponentWithTheSuggestedPrefix: Story = {
  args: { api: buildStructureApi({ components: [], categories: [] }), kind: "component" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "New component" })).toBeDisabled();
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Core Platform");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("CP"));
    await userEvent.click(canvas.getByRole("button", { name: "New component" }));
    await waitFor(() => expect(args.api!.createComponent).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, { name: "Core Platform", prefix: "CP" }));
    await waitFor(() => expect(args.onCreated).toHaveBeenCalled());
    await expect(canvas.getByRole("textbox", { name: "Name" })).toHaveValue("");
  },
};

export const AddsACategoryUnderTheChosenComponent: Story = {
  args: { api: buildStructureApi(), kind: "category", componentId: "c-ops" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Runbooks");
    await waitFor(() => expect(canvas.getByRole("textbox", { name: "Prefix" })).toHaveValue("RUNBOO"));
    await userEvent.click(canvas.getByRole("button", { name: "New category" }));
    await waitFor(() => expect(args.api!.createCategory).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "c-ops", { name: "Runbooks", prefix: "RUNBOO" }));
  },
};

export const ARefusalIsShownBesideTheButton: Story = {
  args: { api: buildStructureApi(), kind: "component" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Name" }), "Another");
    const prefix = canvas.getByRole("textbox", { name: "Prefix" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "SW");
    await userEvent.click(canvas.getByRole("button", { name: "New component" }));
    await expect(await canvas.findByText("A component with this prefix already exists.")).toBeInTheDocument();
  },
};
