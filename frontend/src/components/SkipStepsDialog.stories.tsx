import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { STRESS_TEXT } from "../testing/stressFixtures";
import { SkipStepsDialog } from "./SkipStepsDialog";

/**
 * The dialog of the Skip steps row: the later step to move to (each option names the steps it passes over) and the
 * required reason. The dialog moves nothing itself.
 */
const meta: Meta<typeof SkipStepsDialog> = {
  title: "Components/SkipStepsDialog",
  component: SkipStepsDialog,
  args: {
    noun: "Pain Point",
    options: [
      { value: "accepted", label: "Accepted (skips Triaged)" },
      { value: "addressed", label: "Addressed (skips Triaged, Accepted)" },
    ],
    onClose: fn(),
    onSubmit: fn(async () => undefined),
  },
};
export default meta;

type Story = StoryObj<typeof SkipStepsDialog>;

/** Saving needs a reason; the first option is chosen and the target and the trimmed reason are handed on. */
export const AReasonIsRequired: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    const dialog = within(await body.findByRole("dialog", { name: "Skip steps of this Pain Point" }));
    await expect(requiredCaptions(document.body)).toEqual(["Move to", "Reason"]);
    await expect(dialog.getByRole("button", { name: "Skip steps" })).toBeDisabled();
    await userEvent.type(dialog.getByLabelText(/Reason/), "  Fixed in the hot patch  ");
    await expect(dialog.getByRole("button", { name: "Skip steps" })).toBeEnabled();
    await userEvent.click(dialog.getByRole("button", { name: "Skip steps" }));
    await expect(args.onSubmit).toHaveBeenCalledWith("accepted", "Fixed in the hot patch");
  },
};

export const ChoosingALaterStep: Story = {
  play: async ({ args }) => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: /Move to/ }), "addressed");
    await userEvent.type(dialog.getByLabelText(/Reason/), "Done");
    await userEvent.click(dialog.getByRole("button", { name: "Skip steps" }));
    await expect(args.onSubmit).toHaveBeenCalledWith("addressed", "Done");
  },
};

export const ReasonIsLimited: Story = {
  play: async () => {
    const dialog = within(await within(document.body).findByRole("dialog"));
    await expect(dialog.getByLabelText(/Reason/)).toHaveAttribute("maxlength", "500");
  },
};

/** A very long option and an unbroken word stay inside the dialog. */
export const LongText: Story = {
  args: {
    options: [{ value: "closed", label: `${STRESS_TEXT.name} (skips ${STRESS_TEXT.word})` }],
  },
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), STRESS_TEXT.word.repeat(3));
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth);
  },
};
