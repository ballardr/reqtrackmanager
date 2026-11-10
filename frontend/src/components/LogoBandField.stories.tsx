import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { LogoBandField } from "./LogoBandField";

/** Holds the value, as the settings pages do. */
function Harness({
  initial, initialText = "", platformHex, platformTextHex,
}: { initial: string; initialText?: string; platformHex?: string | null; platformTextHex?: string | null }) {
  const [value, setValue] = useState(initial);
  const [text, setText] = useState(initialText);
  return (
    <LogoBandField
      value={value} onChange={setValue} textValue={text} onTextChange={setText} logoFileId={null} title="Acme Corp"
      platformHex={platformHex} platformTextHex={platformTextHex}
    />
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/LogoBandField",
  component: Harness,
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** No colour chosen: the field shows the top bar colour in use and offers no Remove. */
export const Default: Story = {
  args: { initial: "" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("img", { name: "Preview of the logo band" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    await expect(canvas.queryByText(/hard to see/)).not.toBeInTheDocument();
  },
};

/** An organisation with no colour of its own shows the platform colour. */
export const PlatformFallback: Story = {
  args: { initial: "", platformHex: "#0b5fa5" },
  play: async ({ canvasElement }) => {
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(band?.style.background).toBe("rgb(11, 95, 165)");
  },
};

/** A chosen colour can be removed, returning to the default. */
export const RemoveReturnsToDefault: Story = {
  args: { initial: "#7a1f3d" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvasElement.querySelector<HTMLElement>(".logo-band")?.style.background).toBe("rgb(122, 31, 61)");
    await userEvent.click(canvas.getByRole("button", { name: "Remove" }));
    await expect(canvasElement.querySelector<HTMLElement>(".logo-band")?.style.background).toBe("rgb(20, 22, 28)");
    await expect(canvas.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  },
};

/** A light colour warns that a white logo will be hard to see; it never blocks. */
export const LightColourWarns: Story = {
  args: { initial: "#f5f5f5" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/hard to see/)).toBeInTheDocument();
  },
};

/** With no title colour chosen, the title is black or white by contrast with the band. */
export const TitleFollowsContrast: Story = {
  args: { initial: "#ffffff" },
  play: async ({ canvasElement }) => {
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(band?.style.color).toBe("rgb(0, 0, 0)");
    await expect(within(band as HTMLElement).getByText("Acme Corp")).toBeInTheDocument();
  },
};

/** A chosen title colour is used, and Remove returns to the automatic choice. */
export const TitleColourChosenAndRemoved: Story = {
  args: { initial: "#14161c", initialText: "#ffcc00" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(band?.style.color).toBe("rgb(255, 204, 0)");
    const removes = canvas.getAllByRole("button", { name: "Remove" });
    await userEvent.click(removes[removes.length - 1]); // the title colour's, which follows the band's
    await expect(band?.style.color).toBe("rgb(255, 255, 255)");
  },
};

/** A title colour close to the band warns; it never blocks. */
export const HardToReadTitleWarns: Story = {
  args: { initial: "#14161c", initialText: "#1c1f27" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/hard to read/)).toBeInTheDocument();
  },
};

/** An organisation with no title colour of its own shows the platform one. */
export const PlatformTitleFallback: Story = {
  args: { initial: "", platformTextHex: "#ffcc00" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector<HTMLElement>(".logo-band")?.style.color).toBe("rgb(255, 204, 0)");
  },
};

export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
