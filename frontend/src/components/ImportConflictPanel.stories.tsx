import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { MergeConflict } from "../api/types";
import { defaultResolutions } from "../utils/mergeConflicts";
import { ImportConflictPanel } from "./ImportConflictPanel";

const PROJECT_CONFLICT: MergeConflict = {
  id: "project:P-1", kind: "project", name: "Shared Project Name", existing_id: "11111111-1111-1111-1111-111111111111",
};
const TEMPLATE_CONFLICT: MergeConflict = {
  id: "report_template:Shared Template", kind: "report_template", name: "Shared Template",
  existing_id: "22222222-2222-2222-2222-222222222222",
};

const meta: Meta<typeof ImportConflictPanel> = {
  title: "Components/ImportConflictPanel",
  component: ImportConflictPanel,
  args: { onResolutionChange: fn() },
};
export default meta;

type Story = StoryObj<typeof ImportConflictPanel>;

export const ProjectConflictOnly: Story = {
  args: { conflicts: [PROJECT_CONFLICT], resolutions: defaultResolutions([PROJECT_CONFLICT]) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Shared Project Name")).toBeInTheDocument();
    await expect(canvas.getByRole("radio", { name: "Skip (keep the existing project)" })).toBeChecked();
  },
};

export const ProjectAndTemplateConflicts: Story = {
  args: {
    conflicts: [PROJECT_CONFLICT, TEMPLATE_CONFLICT],
    resolutions: defaultResolutions([PROJECT_CONFLICT, TEMPLATE_CONFLICT]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Projects")).toBeInTheDocument();
    await expect(canvas.getByText("Report templates")).toBeInTheDocument();
    await expect(canvas.getByRole("radio", { name: "Keep the existing template" })).toBeChecked();
  },
};

export const ChangingAResolution: Story = {
  args: { conflicts: [PROJECT_CONFLICT], resolutions: defaultResolutions([PROJECT_CONFLICT]) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("radio", { name: "Import as a new copy" }));
    await expect(args.onResolutionChange).toHaveBeenCalledWith("project:P-1", "import_as_copy");
  },
};

export const LightTheme: Story = { ...ProjectAndTemplateConflicts, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ProjectAndTemplateConflicts, globals: { theme: "dark" } };
