import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { OneTimeSecret } from "./OneTimeSecret";

/** A credential shown once: the title, a sentence saying it cannot be retrieved, the secret, Copy and a dismiss button. */
const meta: Meta<typeof OneTimeSecret> = {
  title: "Components/OneTimeSecret",
  component: OneTimeSecret,
  args: {
    title: "Token issued", hint: "Copy this token now. It is shown once and cannot be retrieved again.",
    secret: "rtm_pat_example_secret", dismissLabel: "I have copied it", onDismiss: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof OneTimeSecret>;

export const ShowsTheSecretAndAWarning: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("rtm_pat_example_secret")).toBeInTheDocument();
    await expect(canvas.getByText(/shown once/)).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "I have copied it" }));
    await expect(args.onDismiss).toHaveBeenCalled();
  },
};
