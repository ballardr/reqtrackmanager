import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { DiagramExportMenu } from "./DiagramExportMenu";

const meta: Meta<typeof DiagramExportMenu> = {
  title: "Modules/Architecture/DiagramExportMenu",
  component: DiagramExportMenu,
  args: { disabled: false, onExport: fn() },
};
export default meta;

type Story = StoryObj<typeof DiagramExportMenu>;

/** The menu offers the two images and the two Mermaid actions, each reporting its kind. */
export const OffersFourExports: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Export" }));
    const menu = within(document.body).getByRole("menu", { name: "Export diagram" });
    for (const name of ["PNG image", "SVG image", "Download Mermaid text", "Copy Mermaid text"]) {
      await expect(within(menu).getByRole("menuitem", { name })).toBeInTheDocument();
    }
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Copy Mermaid text" }));
    await expect(args.onExport).toHaveBeenCalledWith("copy-mermaid");
  },
};

/** While an export is in progress the button is unavailable. */
export const UnavailableWhileExporting: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Export" })).toBeDisabled();
  },
};
