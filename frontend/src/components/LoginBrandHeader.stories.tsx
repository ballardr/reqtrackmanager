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
  args: { logoFileId: "00000000-0000-0000-0000-000000000000", title: "Acme Corp", bandColorHex: null },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    // alt="" is intentional (decorative — the title text already conveys the
    // same info), which removes it from the a11y tree, so query by tag.
    await expect(canvasElement.querySelector("img")).toBeInTheDocument();
  },
};

/** No logo set (platform default with no override, or an org that never
 * uploaded one) — falls back to the built-in logo mark rather than
 * rendering no image at all. */
export const NoLogo: Story = {
  args: { logoFileId: null, title: "ReqTrack", bandColorHex: null },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ReqTrack")).toBeInTheDocument();
    const img = canvasElement.querySelector("img");
    await expect(img).toBeInTheDocument();
    // Falls back to the bundled asset (a `builtInLogo` import, hashed by
    // Vite at build time), not a `fileUrl(...)` API path.
    await expect(img?.getAttribute("src")).not.toMatch(/\/api\//);
  },
};

/** With no band colour chosen, the band follows the top bar colour (the stylesheet variable). */
export const DefaultBand: Story = {
  args: { logoFileId: null, title: "ReqTrack", bandColorHex: null },
  play: async ({ canvasElement }) => {
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(band).toBeInTheDocument();
    await expect(band?.style.background).toContain("var(--color-header-bg)");
  },
};

/** The title is drawn on the band beside the logo, in black or white by contrast, or in the chosen colour. */
export const TitleOnTheBand: Story = {
  args: { logoFileId: null, title: "Acme Corp", bandColorHex: "#ffffff" },
  play: async ({ canvasElement }) => {
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(within(band as HTMLElement).getByRole("heading", { name: "Acme Corp" })).toBeInTheDocument();
    await expect(band?.style.color).toBe("rgb(0, 0, 0)");
  },
};

export const ChosenTitleColour: Story = {
  args: { logoFileId: null, title: "Acme Corp", bandColorHex: "#0b5fa5", bandTextColorHex: "#ffe9a8" },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector<HTMLElement>(".logo-band")?.style.color).toBe("rgb(255, 233, 168)");
  },
};

/** A chosen colour is drawn behind the logo, running edge to edge across the top of the card. */
export const CustomBand: Story = {
  args: { logoFileId: null, title: "Acme Corp", bandColorHex: "#0b5fa5" },
  play: async ({ canvasElement }) => {
    const band = canvasElement.querySelector<HTMLElement>(".logo-band");
    await expect(band?.style.background).toBe("rgb(11, 95, 165)");
    // Edge to edge: the band is as wide as the card it sits in.
    const card = canvasElement.querySelector<HTMLElement>(".card");
    const gap = (card?.getBoundingClientRect().width ?? 0) - (band?.getBoundingClientRect().width ?? 0);
    await expect(gap).toBeLessThan(3);
  },
};

export const LightTheme: Story = { ...WithLogo, globals: { theme: "light" } };
export const DarkTheme: Story = { ...WithLogo, globals: { theme: "dark" } };
