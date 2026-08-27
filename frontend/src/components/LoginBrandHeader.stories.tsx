import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { LoginBrandHeader } from "./LoginBrandHeader";

const meta: Meta<typeof LoginBrandHeader> = {
  title: "Components/LoginBrandHeader",
  component: LoginBrandHeader,
  decorators: [(Story) => <div className="card stack" style={{ maxWidth: 380 }}><Story /></div>],
};
export default meta;

type Story = StoryObj<typeof LoginBrandHeader>;

export const WithLogo: Story = {
  args: { logoFileId: "00000000-0000-0000-0000-000000000000", title: "Acme Corp" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    // alt="" is intentional (decorative — the title text already conveys the
    // same info), which removes it from the a11y tree, so query by tag.
    await expect(canvasElement.querySelector("img")).toBeInTheDocument();
  },
};

/** No logo set (platform default with no override, or an org that never
 * uploaded one) — falls back to title-only, no broken image. */
export const NoLogo: Story = {
  args: { logoFileId: null, title: "ReqTrack" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ReqTrack")).toBeInTheDocument();
    await expect(canvasElement.querySelector("img")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...WithLogo, globals: { theme: "light" } };
export const DarkTheme: Story = { ...WithLogo, globals: { theme: "dark" } };
