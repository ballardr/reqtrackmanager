import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { EMPTY_REVIEW_VALUES } from "./policyText";
import { DANA, ORG_ID, ORG_USERS } from "./policyFixtures";
import { ReviewSettingsFields } from "./ReviewSettingsFields";
import type { ReviewSettingsValues } from "./types";

/** Holds the values the fields edit, and reports each change to `onChange`. */
function Harness({ initial, onChange }: { initial: ReviewSettingsValues; onChange: (values: ReviewSettingsValues) => void }) {
  const [values, setValues] = useState(initial);
  return (
    <ReviewSettingsFields
      values={values} orgUsers={ORG_USERS} organizationId={ORG_ID} ownerDisplay={DANA}
      onChange={(next) => { setValues(next); onChange(next); }}
    />
  );
}

const meta: Meta<typeof Harness> = {
  title: "Modules/Governance/ReviewSettingsFields",
  component: Harness,
  args: { initial: { interval_days: 90, lead_days: 14, default_owner: { type: "user", id: "user-1" } }, onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const ShowsTheCurrentSettings: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Review interval (days)")).toHaveValue(90);
    await expect(canvas.getByLabelText("Reminder lead (days)")).toHaveValue(14);
    await expect(canvas.getByText("Dana Whitfield")).toBeInTheDocument();
  },
};

export const ChangingANumberReportsIt: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const interval = canvas.getByLabelText("Review interval (days)");
    await userEvent.clear(interval);
    await userEvent.type(interval, "30");
    await expect(args.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ interval_days: 30 }));
  },
};

export const AnEmptyNumberIsUnset: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.clear(canvas.getByLabelText("Reminder lead (days)"));
    await expect(args.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ lead_days: null }));
  },
};

export const NothingSet: Story = {
  args: { initial: EMPTY_REVIEW_VALUES },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Review interval (days)")).toHaveValue(null);
    await expect(canvas.getByText("Not set")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsTheCurrentSettings, globals: { theme: "dark" } };
