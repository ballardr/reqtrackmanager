import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ProposedLinkRow } from "./ProposedLinkRow";

/** One proposed link, drawn like a row of the Links panel. */
const meta: Meta<typeof ProposedLinkRow> = {
  title: "Components/ProposedLinkRow",
  component: ProposedLinkRow,
  decorators: [(Story) => <ul className="artefact-links__list"><Story /></ul>],
  args: { view: { phrase: "Depends on", label: "AUTH-002 — Passwords expire", typeLabel: "Requirement" } },
};
export default meta;

type Story = StoryObj<typeof ProposedLinkRow>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Depends on")).toBeInTheDocument();
    await expect(canvas.getByText("Requirement")).toBeInTheDocument();
  },
};

/** A record the viewer cannot see is a neutral placeholder, never its title. */
export const HiddenRecord: Story = {
  args: { view: { phrase: "Depends on", label: null, typeLabel: "Decision" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("A record you cannot see")).toBeInTheDocument();
  },
};

export const WithProjectAndControls: Story = {
  args: {
    view: { phrase: "Depends on", label: "AUTH-002", typeLabel: "Requirement", projectName: "Programme" },
    leading: <input type="checkbox" aria-label="Merge" />,
    trailing: <span className="text-muted">Already linked, will be skipped</span>,
    muted: true,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("In Programme")).toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Merge" })).toBeInTheDocument();
  },
};
