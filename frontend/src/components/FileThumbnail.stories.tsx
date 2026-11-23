import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { FileThumbnail } from "./FileThumbnail";

/** The preview beside a file's name in a file list: the picture on its backdrop for a picture, a bare icon for any other file. */
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

/** Asserts the type icon has no fill and is the same square as a picture's thumbnail. */
function expectBareIcon(canvasElement: HTMLElement) {
  const icon = canvasElement.querySelector(".file-thumb--icon") as HTMLElement;
  const style = getComputedStyle(icon);
  expect(style.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(style.backgroundImage).toBe("none");
  expect(icon.getBoundingClientRect().width).toBe(icon.getBoundingClientRect().height);
}

/** A type icon is drawn with no background (the picture's backdrop is not applied to it), at the picture's size. */
export const ATypeIconHasNoBackground: Story = {
  args: { file: { id: "f5", filename: "spec.pdf", content_type: "application/pdf" } },
  play: ({ canvasElement }) => expectBareIcon(canvasElement),
};

/** A picture keeps its backdrop: the checkerboard by default, so a transparent picture stays visible. */
export const APictureKeepsItsBackdrop: Story = {
  args: { file: { id: "f6", filename: "mark.png", content_type: "image/png" } },
  play: async ({ canvasElement }) => {
    const picture = within(canvasElement).getByRole("img", { name: "mark.png" });
    await expect(picture.classList.contains("picture-backdrop")).toBe(true);
    await expect(getComputedStyle(picture).backgroundImage).not.toBe("none");
  },
};

/** The same bare icon in the dark theme has no fill either. */
export const ATypeIconIsBareInTheDarkTheme: Story = {
  args: { file: { id: "f7", filename: "spec.pdf", content_type: "application/pdf" } },
  decorators: [
    (Story) => {
      document.documentElement.dataset.theme = "dark";
      return <Story />;
    },
  ],
  play: ({ canvasElement }) => {
    try {
      expectBareIcon(canvasElement);
    } finally {
      delete document.documentElement.dataset.theme;
    }
  },
};

/** A picture the browser cannot read falls back to the icon. */
export const AnUnreadablePictureFallsBackToTheIcon: Story = {
  args: { file: { id: "f4", filename: "broken.png", content_type: "image/png" } },
  play: async ({ canvasElement }) => {
    within(canvasElement).getByRole("img", { name: "broken.png" }).dispatchEvent(new Event("error"));
    await waitFor(() => expect(canvasElement.querySelector(".file-thumb--icon")).not.toBeNull());
    expectBareIcon(canvasElement);
  },
};
