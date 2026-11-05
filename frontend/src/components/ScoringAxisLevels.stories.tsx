import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, waitFor, within } from "storybook/test";

import { buildCustomCriteriaScheme, buildUser, expandScoringLevels, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ScoringAxisLevels } from "./ScoringAxisLevels";

const PROJECT_ID = "project-1";

const calls = () => ({ create: fn(async () => ({})), update: fn(async () => ({})), remove: fn(async () => ({})) });

const meta: Meta<typeof ScoringAxisLevels> = {
  title: "Components/Scoring/ScoringAxisLevels",
  component: ScoringAxisLevels,
  args: { scheme: buildCustomCriteriaScheme(), calls: calls(), onChanged: fn() },
  // Each axis folds, and remembers it, through the signed-in person's preferences.
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof ScoringAxisLevels>;

/** Every axis starts folded to its name and level count; opening one shows its levels as a grid under headings. */
export const FoldedUntilOpened: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("textbox", { name: /level name/ })).not.toBeInTheDocument();
    await expect(canvas.getAllByText(/\d+ levels/).length).toBeGreaterThan(1);
    await expandScoringLevels(canvas);
    await expect(canvas.getAllByRole("textbox", { name: /level name/ }).length).toBeGreaterThan(0);
    await expect(canvas.getAllByText("Guidance").length).toBeGreaterThan(0);
  },
};

/** In a project, an axis the organisation defined shows the same columns read-only; no field or delete is offered. */
export const OrganisationAxesAreReadOnlyInAProject: Story = {
  args: { projectId: PROJECT_ID },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expandScoringLevels(canvas);
    await expect(canvas.queryByRole("textbox", { name: /level name/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Delete .* level/ })).not.toBeInTheDocument();
    await waitFor(() => expect(canvas.getAllByText("Weight").length).toBeGreaterThan(0));
  },
};
