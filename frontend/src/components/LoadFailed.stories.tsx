import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LoadFailed } from "./LoadFailed";

/** The failed-load line of a page that would otherwise show a spinner for ever. */
const meta: Meta<typeof LoadFailed> = {
  title: "Components/LoadFailed",
  component: LoadFailed,
  args: { message: "The organisation list could not be loaded.", onRetry: fn() },
};
export default meta;

type Story = StoryObj<typeof LoadFailed>;

export const NamesWhatFailedAndRetries: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent("The organisation list could not be loaded.");
    await userEvent.click(canvas.getByRole("button", { name: "Retry" }));
    await expect(args.onRetry).toHaveBeenCalledTimes(1);
  },
};

export const LongMessageKeepsRetryOnItsLine: Story = {
  args: { message: "The reviews due for a requirement with an exceptionally long name could not be loaded because the server did not answer." },
  decorators: [(Story) => <div style={{ width: "28rem" }}><Story /></div>],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Retry" })).toBeVisible();
  },
};
