import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { PhaseRangeEditor } from "./PhaseRangeEditor";

/** The dialog for one phase's expected range: two calendar dates, both empty to remove the schedule. */
const meta: Meta<typeof PhaseRangeEditor> = {
  title: "Components/PhaseRangeEditor",
  component: PhaseRangeEditor,
  args: { title: "Release 1: Review", expectedFrom: null, expectedTo: null, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof PhaseRangeEditor>;

/** Saving sends both dates as entered. */
export const SavesBothDates: Story = {
  play: async ({ args }) => {
    const body = within(await within(document.body).findByRole("dialog"));
    await userEvent.type(await body.findByLabelText("Expected start"), "2026-12-01");
    await userEvent.type(body.getByLabelText("Expected end"), "2026-12-10");
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith("2026-12-01", "2026-12-10");
  },
};

/** Emptying both dates saves nulls, which removes the schedule. */
export const EmptyingBothClearsTheRange: Story = {
  args: { expectedFrom: "2026-12-01", expectedTo: "2026-12-10" },
  play: async ({ args }) => {
    const body = within(await within(document.body).findByRole("dialog"));
    await userEvent.clear(await body.findByLabelText("Expected start"));
    await userEvent.clear(body.getByLabelText("Expected end"));
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(null, null);
  },
};

/** An end before the start is refused in the dialog before anything is sent. */
export const EndBeforeStartCannotBeSaved: Story = {
  args: { expectedFrom: "2026-12-10", expectedTo: "2026-12-01" },
  play: async () => {
    const body = within(await within(document.body).findByRole("dialog"));
    await expect(await body.findByText("The expected end must not be before the expected start.")).toBeInTheDocument();
    await expect(body.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** A save error from the server is shown in the dialog. */
export const ShowsTheServerError: Story = {
  args: { error: "Component phases are off for this project." },
  play: async () => {
    await expect(await within(await within(document.body).findByRole("dialog")).findByText("Component phases are off for this project.")).toBeInTheDocument();
  },
};
