import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { HelpRedirectPage } from "./HelpRedirectPage";

const replace = fn();

const meta: Meta<typeof HelpRedirectPage> = {
  title: "Pages/HelpRedirectPage",
  component: HelpRedirectPage,
  args: { replace },
  beforeEach: () => {
    replace.mockClear();
  },
};
export default meta;

type Story = StoryObj<typeof HelpRedirectPage>;

/** An old `/help` bookmark is sent on to the configured help URL. */
export const RedirectsToConfiguredUrl: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ help_enabled: true, help_url: "https://docs.example.com/" });
  },
  play: async () => {
    await waitFor(() => expect(replace).toHaveBeenCalledWith("https://docs.example.com/"));
  },
};

/** With Help turned off there is nowhere to go, so the page says so instead of redirecting. */
export const NotConfiguredWhenDisabled: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ help_enabled: false, help_url: "https://docs.example.com/" });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Help is not configured for this deployment.")).toBeInTheDocument();
    await expect(replace).not.toHaveBeenCalled();
  },
};
