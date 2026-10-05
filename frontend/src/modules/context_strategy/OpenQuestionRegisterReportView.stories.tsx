import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, within } from "storybook/test";

import { withRouter } from "../../testing/storybook-helpers";
import { OpenQuestionRegisterReportView } from "./OpenQuestionRegisterReportView";
import { registerEntry, registerResult } from "./reportFixtures";

const meta: Meta<typeof OpenQuestionRegisterReportView> = {
  title: "Modules/ContextStrategy/Reports/OpenQuestionRegisterReportView",
  component: OpenQuestionRegisterReportView,
  decorators: [withRouter("/projects/project-1/reports")],
  args: {
    entry: registerEntry(), result: registerResult(), scope: { kind: "project", id: "project-1" },
    values: {}, onValueChange: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof OpenQuestionRegisterReportView>;

/** Overdue and unowned questions are flagged in the one table, so the reader need not cross-reference two lists. */
export const HighlightsOverdueAndUnowned: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const overdue = canvas.getByRole("row", { name: /Is SSO required at launch/ });
    await expect(within(overdue).getByText("Overdue")).toBeInTheDocument();
    await expect(within(overdue).getByText("Investigating")).toBeInTheDocument();
    const unowned = canvas.getByRole("row", { name: /Who signs off the budget/ });
    await expect(within(unowned).getByText("Unowned")).toBeInTheDocument();
    await expect(within(unowned).getByText("Ready for Decision")).toBeInTheDocument();
    const healthy = canvas.getByRole("row", { name: /Which regions are in scope/ });
    await expect(within(healthy).queryByText("Overdue")).not.toBeInTheDocument();
    await expect(within(healthy).getByText("Alex Owner")).toBeInTheDocument();
    await expect(within(healthy).getByText("High")).toBeInTheDocument();
  },
};

/** The register and its two gap lists are replaced by the table; the counts remain. */
export const KeepsCountSectionsOnly: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("region", { name: "By priority" })).toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Overdue" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Unowned" })).not.toBeInTheDocument();
  },
};

export const OrganisationScopeShowsProject: Story = {
  args: { scope: { kind: "organization", id: "org-1" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("columnheader", { name: "Project" })).toBeInTheDocument();
  },
};

export const NoOpenQuestions: Story = {
  args: { result: registerResult({ data: { items: [] } }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No open Open Questions.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...HighlightsOverdueAndUnowned, globals: { theme: "light" } };
export const DarkTheme: Story = { ...HighlightsOverdueAndUnowned, globals: { theme: "dark" } };
