import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ImportWarnings } from "./ImportWarnings";

const meta: Meta<typeof ImportWarnings> = {
  title: "Components/ImportWarnings",
  component: ImportWarnings,
  args: { warnings: ["Level 'High' was not found and was skipped.", "A tag was renamed."] },
};
export default meta;

type Story = StoryObj<typeof ImportWarnings>;

export const Card: Story = {
  args: { title: "Imported with warnings" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Imported with warnings")).toBeVisible();
    await expect(canvas.getAllByRole("listitem")).toHaveLength(2);
  },
};

export const BareList: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("listitem")).toHaveLength(2);
    await expect(canvas.queryByRole("status")).toBeNull();
  },
};

export const NoWarnings: Story = {
  args: { warnings: [], title: "Imported with warnings" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("status")).toBeNull();
    await expect(canvas.queryByRole("listitem")).toBeNull();
  },
};

export const DarkTheme: Story = {
  globals: { theme: "dark" },
  args: { title: "Imported with warnings" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Imported with warnings")).toBeVisible();
  },
};
