import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LabeledSelect } from "./LabeledSelect";
import { MultiSelectDropdown } from "./MultiSelectDropdown";

const meta: Meta<typeof LabeledSelect> = {
  title: "Components/LabeledSelect",
  component: LabeledSelect,
  args: {
    label: "Standard",
    value: "",
    onChange: fn(),
    options: [
      { value: "std-1", label: "ISO-27001 — Corporate Security Standard" },
      { value: "std-2", label: "SOC2 — Trust Services Criteria" },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof LabeledSelect>;

export const SelectingCallsOnChange: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByLabelText("Standard");
    await expect(select).toBeEnabled();
    await userEvent.selectOptions(select, "std-2");
    await expect(args.onChange).toHaveBeenCalledWith("std-2");
  },
};

export const DisabledUntilParentChosen: Story = {
  args: { label: "Version", disabled: true, placeholder: "Select a standard first…" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Version")).toBeDisabled();
    await expect(canvas.getByRole("option", { name: "Select a standard first…" })).toBeInTheDocument();
  },
};

/** `placeholder={null}` omits the blank option, for a select that always
 * holds a value (e.g. a scoring-model switcher). */
export const NoPlaceholder: Story = {
  args: { label: "Model", value: "a", placeholder: null, options: [{ value: "a", label: "A" }, { value: "b", label: "B" }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("option")).toHaveLength(2);
    await expect(canvas.getByLabelText("Model")).toHaveValue("a");
  },
};

/** Every select draws the same chevron at the same distance from its right edge, and so does the custom dropdown beside it. */
export const SelectChevronsLineUpWithTheCustomDropdown: Story = {
  render: () => (
    <div className="stack" style={{ width: 280 }}>
      <LabeledSelect helpNotNeeded label="First" value="" onChange={() => {}} options={[{ value: "a", label: "A" }]} />
      <LabeledSelect helpNotNeeded label="Second" value="a" onChange={() => {}} options={[{ value: "a", label: "A much longer value than the first" }]} />
      <MultiSelectDropdown triggerLabel="Tags" options={[{ value: "t", label: "T", checked: false, optionLabel: "Tag T", onToggle: () => {} }]} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Tags" });
    // The dropdown's chevron: its right edge's distance from the trigger's outer right edge.
    const gap = (el: Element, right: number) => el.getBoundingClientRect().right - right;
    const dropdownGap = gap(trigger, trigger.querySelector("svg")!.getBoundingClientRect().right);
    for (const name of ["First", "Second"]) {
      const select = canvas.getByLabelText(name);
      const style = getComputedStyle(select);
      await expect(style.appearance).toBe("none");
      // background-position `right 0.6rem` is measured from the padding box, so add the border.
      const chevronGap = parseFloat(style.borderRightWidth) + 0.6 * parseFloat(getComputedStyle(document.documentElement).fontSize);
      await expect(Math.abs(chevronGap - dropdownGap)).toBeLessThan(1);
    }
  },
};
