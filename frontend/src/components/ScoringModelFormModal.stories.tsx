import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { buildCustomCriteriaScheme } from "../testing/storybook-helpers";
import { ScoringModelFormModal } from "./ScoringModelFormModal";

const scheme = buildCustomCriteriaScheme();

const meta: Meta<typeof ScoringModelFormModal> = {
  title: "Components/Scoring/ScoringModelFormModal",
  component: ScoringModelFormModal,
  args: { axes: scheme.axes, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof ScoringModelFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** A product needs a name and at least one multiplied axis; an axis can be divided by, with an exponent. */
export const ProductNeedsAMultipliedAxis: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Name"]);
    const save = d.getByRole("button", { name: "Save" });
    await userEvent.type(d.getByLabelText("Name"), "Value for money");
    await expect(save).toBeDisabled();
    await expect(d.getByText("Multiply by at least one axis.")).toBeInTheDocument();
    await userEvent.selectOptions(d.getByLabelText("Impact role"), "multiply");
    await userEvent.selectOptions(d.getByLabelText("Strategic fit role"), "divide");
    await userEvent.clear(d.getByLabelText("Impact exponent"));
    await userEvent.type(d.getByLabelText("Impact exponent"), "2");
    await userEvent.click(save);
    await expect(args.onSave).toHaveBeenCalledWith({
      label: "Value for money", combination: "product",
      axes: [{ axis_key: "impact", role: "multiply", exponent: 2 }, { axis_key: "c_strategic_fit", role: "divide", exponent: 1 }],
    });
  },
};

/** A weighted sum saves only when the importances total 100 per cent. */
export const WeightedSumMustTotalOneHundred: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "Blend");
    await userEvent.selectOptions(d.getByLabelText("Combination"), "weighted_sum");
    await userEvent.selectOptions(d.getByLabelText("Impact role"), "sum");
    await userEvent.selectOptions(d.getByLabelText("Strategic fit role"), "sum");
    await userEvent.type(d.getByLabelText("Impact importance"), "70");
    await userEvent.type(d.getByLabelText("Strategic fit importance"), "20");
    const save = d.getByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await expect(d.getByText("Importance totals 90%; it must total 100%.")).toBeInTheDocument();
    await userEvent.clear(d.getByLabelText("Strategic fit importance"));
    await userEvent.type(d.getByLabelText("Strategic fit importance"), "30");
    await userEvent.click(d.getByRole("checkbox", { name: "Strategic fit lower is better" }));
    await userEvent.click(save);
    await expect(args.onSave).toHaveBeenCalledWith({
      label: "Blend", combination: "weighted_sum",
      axes: [
        { axis_key: "impact", role: "sum", importance: 70, lower_is_better: false },
        { axis_key: "c_strategic_fit", role: "sum", importance: 30, lower_is_better: true },
      ],
    });
  },
};

/** Editing starts from the model's own combination, roles and importances. */
export const EditStartsFromTheModel: Story = {
  args: { initial: scheme.models[1] },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("heading", { name: "Edit scoring model" })).toBeInTheDocument();
    await expect(d.getByLabelText("Name")).toHaveValue("Weighted value");
    await expect(d.getByLabelText("Combination")).toHaveValue("weighted_sum");
    await expect(d.getByLabelText("Impact importance")).toHaveValue(60);
    await expect(d.getByLabelText("Strategic fit importance")).toHaveValue(40);
    await expect(d.getByLabelText("Demand role")).toHaveValue("none");
    await expect(d.getByRole("button", { name: "Save" })).toBeEnabled();
  },
};
