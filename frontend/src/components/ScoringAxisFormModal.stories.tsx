import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { buildCustomCriteriaScheme } from "../testing/storybook-helpers";
import { ScoringAxisFormModal } from "./ScoringAxisFormModal";

const meta: Meta<typeof ScoringAxisFormModal> = {
  title: "Components/Scoring/ScoringAxisFormModal",
  component: ScoringAxisFormModal,
  args: { onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof ScoringAxisFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Saving needs a name and two levels with distinct names and weights; only the name is marked required. */
export const CreateNeedsANameAndTwoLevels: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    const save = d.getByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await userEvent.type(d.getByLabelText("Name"), "Strategic fit");
    await userEvent.type(d.getByLabelText("Level 1 name"), "Weak");
    await userEvent.type(d.getByLabelText("Level 1 weight"), "1");
    await userEvent.type(d.getByLabelText("Level 2 name"), "Strong");
    await userEvent.type(d.getByLabelText("Level 2 weight"), "1");
    await expect(save).toBeDisabled(); // repeated weight
    await userEvent.clear(d.getByLabelText("Level 2 weight"));
    await userEvent.type(d.getByLabelText("Level 2 weight"), "3");
    await userEvent.click(save);
    await expect(args.onSave).toHaveBeenCalledWith({
      label: "Strategic fit", description: null,
      levels: [{ name: "Weak", weight: 1, description: null }, { name: "Strong", weight: 3, description: null }],
    });
  },
};

/** Levels can be added, and removed down to the floor of two. */
export const LevelsAddAndRemoveDownToTwo: Story = {
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Remove level 1" })).toBeDisabled();
    await userEvent.click(d.getByRole("button", { name: "Add level" }));
    await expect(d.getByLabelText("Level 3 name")).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Remove level 3" }));
    await expect(d.queryByLabelText("Level 3 name")).not.toBeInTheDocument();
  },
};

/** Editing changes the name and guidance only; levels are edited in the scheme editor. */
export const EditStartsFromTheAxis: Story = {
  args: { initial: buildCustomCriteriaScheme().axes[2] },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("heading", { name: "Edit scoring axis" })).toBeInTheDocument();
    await expect(d.getByLabelText("Name")).toHaveValue("Strategic fit");
    await expect(d.getByLabelText("Guidance")).toHaveValue("How well it fits the plan.");
    await expect(d.queryByLabelText("Level 1 name")).not.toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const ShowsASaveError: Story = {
  args: { error: "An axis with this name already exists here." },
  play: async () => {
    await expect(dialog().getByText("An axis with this name already exists here.")).toBeInTheDocument();
  },
};

/** On a scheme with targets the axis chooses whether it is scored once for the record or per target; the default is the whole record. */
export const ScoredPerTargetOrForTheWholeRecord: Story = {
  args: { targetLabel: "persona" },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByLabelText("Scored")).toHaveValue("whole");
    await userEvent.selectOptions(d.getByLabelText("Scored"), "target");
    await userEvent.type(d.getByLabelText("Name"), "Revenue risk");
    await userEvent.type(d.getByLabelText("Level 1 name"), "Low");
    await userEvent.type(d.getByLabelText("Level 1 weight"), "1");
    await userEvent.type(d.getByLabelText("Level 2 name"), "High");
    await userEvent.type(d.getByLabelText("Level 2 weight"), "3");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      label: "Revenue risk", description: null, per_target: true,
      levels: [{ name: "Low", weight: 1, description: null }, { name: "High", weight: 3, description: null }],
    });
  },
};

/** A scheme with no targets offers no choice and sends none. */
export const NoScopeChoiceWithoutTargets: Story = {
  play: async () => {
    await expect(dialog().queryByLabelText("Scored")).not.toBeInTheDocument();
  },
};

/** Editing keeps the choice fixed, so the field is not offered. */
export const EditDoesNotOfferTheScope: Story = {
  args: { initial: buildCustomCriteriaScheme().axes[2], targetLabel: "persona" },
  play: async () => {
    await expect(dialog().queryByLabelText("Scored")).not.toBeInTheDocument();
  },
};
