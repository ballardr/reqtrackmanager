import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildCustomCriteriaScheme, buildUser, expandScoringLevels, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
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

/** In a project, a derived axis (Demand) is the one organisation axis whose thresholds the project can set, beside the organisation's own. */
export const ADerivedAxisTakesTheProjectsOwnThresholds: Story = {
  args: { projectId: PROJECT_ID, thresholdCalls: { save: fn(async () => ({})) } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expandScoringLevels(canvas);
    await expect(canvas.getByText("From (this project)")).toBeInTheDocument();
    const field = canvas.getByRole("spinbutton", { name: "Demand Lots threshold in this project" });
    await expect(field).toHaveValue(10);
    await userEvent.clear(field);
    await userEvent.type(field, "40");
    await userEvent.click(canvas.getByRole("button", { name: "Save thresholds" }));
    await waitFor(() => expect(args.thresholdCalls!.save).toHaveBeenCalledWith("demand", { "dem-1": 0, "dem-2": 3, "dem-3": 40 }));
    // An ordinary organisation axis stays read-only.
    await expect(canvas.queryByRole("spinbutton", { name: /Impact .* threshold/ })).not.toBeInTheDocument();
  },
};

/** Long axis labels, level names and guidance, editable and read-only: every row keeps its columns and its buttons. */
export const LongText: Story = {
  render: (args) => (
    <TextStress
      width={720}
      render={(long) => {
        const base = buildCustomCriteriaScheme();
        const scheme = buildCustomCriteriaScheme({
          axes: base.axes.map((axis, index) => ({
            ...axis,
            label: index === 0 ? stressText(long, axis.label) : axis.label,
            levels: axis.levels.map((level, at) => ({
              ...level,
              name: at === 0 ? stressText(long, level.name, "word") : level.name,
              description: at === 1 ? stressText(long, "", "summary") : level.description,
            })),
          })),
        });
        return <ScoringAxisLevels {...args} scheme={scheme} />;
      }}
    />
  ),
  play: async ({ canvasElement }) => {
    // Open every axis in both renders, then measure.
    for (const root of Array.from(canvasElement.querySelectorAll<HTMLElement>("[data-stress]"))) {
      await expandScoringLevels(within(root));
    }
    await expectStressStable(canvasElement);
  },
};

/** The same, as a project reads the organisation's axes (read-only plain cells). */
export const LongTextReadOnlyInAProject: Story = {
  ...LongText,
  args: { projectId: PROJECT_ID },
};
