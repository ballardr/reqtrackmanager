import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { FileThumbnail } from "./FileThumbnail";

/** The preview beside a file's name in a file list: the picture for a picture, an icon for any other file. */
const meta: Meta<typeof FileThumbnail> = {
  title: "Components/FileThumbnail",
  component: FileThumbnail,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof FileThumbnail>;

export const APictureIsDrawnLazilyWithItsNameAsAlt: Story = {
  args: { file: { id: "f1", filename: "gate.jpg", content_type: "image/jpeg" } },
  play: async ({ canvasElement }) => {
    const picture = within(canvasElement).getByRole("img", { name: "gate.jpg" });
    await expect(picture.getAttribute("src")).toContain("/api/v1/files/f1");
    await expect(picture.getAttribute("loading")).toBe("lazy");
  },
};

/** An SVG is drawn by an image element, never inlined into the page. */
export const AnSvgIsDrawnAsAnImageNotInlined: Story = {
  args: { file: { id: "f2", filename: "logo.svg", content_type: "image/svg+xml" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("img", { name: "logo.svg" }).tagName).toBe("IMG");
    await expect(canvasElement.querySelector("svg:not([aria-hidden])")).toBeNull();
  },
};

/** A file that is not a picture shows an icon and makes no request. */
export const ADocumentShowsAnIcon: Story = {
  args: { file: { id: "f3", filename: "spec.pdf", content_type: "application/pdf" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("img")).toBeNull();
    await expect(canvasElement.querySelector(".file-thumb--icon")).not.toBeNull();
  },
};

/** A picture the browser cannot read falls back to the icon. */
export const AnUnreadablePictureFallsBackToTheIcon: Story = {
  args: { file: { id: "f4", filename: "broken.png", content_type: "image/png" } },
  play: async ({ canvasElement }) => {
    within(canvasElement).getByRole("img", { name: "broken.png" }).dispatchEvent(new Event("error"));
    await waitFor(() => expect(canvasElement.querySelector(".file-thumb--icon")).not.toBeNull());
  },
};
