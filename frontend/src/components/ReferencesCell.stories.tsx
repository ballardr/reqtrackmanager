import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildReference } from "../testing/referencesFixtures";
import { ReferencesCell } from "./ReferencesCell";

/** A record's external references as one table cell: the key opens the item when the reference has a web link. */
const meta: Meta<typeof ReferencesCell> = { title: "Components/ReferencesCell", component: ReferencesCell };
export default meta;

type Story = StoryObj<typeof ReferencesCell>;

export const LinksTheKeyOnlyWhenThereIsAWebLink: Story = {
  args: { references: [buildReference(), buildReference({ key: "REQ-9", link: null }, "s-doors"), buildReference({ key: "BAD-1", link: "javascript:alert(1)" })] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Open Jira: PROJ-1 in a new tab" })).toHaveAttribute("rel", "noopener noreferrer");
    await expect(canvas.getByText(/DOORS:/)).toBeInTheDocument();
    await expect(canvas.getAllByRole("link")).toHaveLength(1);
  },
};

export const DrawsNothingForARecordWithNone: Story = {
  args: { references: [] },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.textContent).toBe("");
  },
};
