import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { withPictureFiles } from "../testing/pictureFiles";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { FileThumbnail } from "./FileThumbnail";

/** The preview beside a file's name in a file list: the picture on its backdrop, as a button that opens a larger preview, for a picture; a bare icon for any other file. */
const meta: Meta<typeof FileThumbnail> = {
  title: "Components/FileThumbnail",
  component: FileThumbnail,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withPictureFiles],
};
export default meta;

type Story = StoryObj<typeof FileThumbnail>;

export const APictureIsDrawnLazilyInAPreviewButton: Story = {
  args: { file: { id: "pic-png", filename: "gate.jpg", content_type: "image/jpeg" } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Preview gate.jpg" });
    const picture = button.querySelector("img") as HTMLImageElement;
    await expect(picture.getAttribute("loading")).toBe("lazy");
    await expect(picture.getAttribute("alt")).toBe("");
  },
};

/** An SVG is drawn by an image element, never inlined into the page. */
export const AnSvgIsDrawnAsAnImageNotInlined: Story = {
  args: { file: { id: "pic-svg", filename: "logo.svg", content_type: "image/svg+xml" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Preview logo.svg" }).querySelector("img")).not.toBeNull();
    await expect(canvasElement.querySelector("svg:not([aria-hidden])")).toBeNull();
  },
};

/** A file that is not a picture shows an icon and makes no request. */
export const ADocumentShowsAnIcon: Story = {
  args: { file: { id: "f3", filename: "spec.pdf", content_type: "application/pdf" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("img")).toBeNull();
    await expect(within(canvasElement).queryByRole("button")).toBeNull();
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
  args: { file: { id: "pic-png", filename: "mark.png", content_type: "image/png" } },
  play: async ({ canvasElement }) => {
    const picture = within(canvasElement).getByRole("button", { name: "Preview mark.png" }).querySelector("img") as HTMLImageElement;
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
    within(canvasElement).getByRole("button", { name: "Preview broken.png" }).querySelector("img")?.dispatchEvent(new Event("error"));
    await waitFor(() => expect(canvasElement.querySelector(".file-thumb--icon")).not.toBeNull());
    await expect(within(canvasElement).queryByRole("button")).toBeNull();
    expectBareIcon(canvasElement);
  },
};

/** Clicking the thumbnail opens the larger preview of the same file; Escape closes it and focus returns to the thumbnail. */
export const ClickingThePictureOpensThePreview: Story = {
  args: { file: { id: "pic-png", filename: "logo.png", content_type: "image/png" } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Preview logo.png" });
    await userEvent.click(button);
    const dialog = await within(document.body).findByRole("dialog", { name: "logo.png" });
    await expect(within(dialog).getByRole("img", { name: "logo.png" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(button));
  },
};

/** The thumbnail opens from the keyboard (Enter) and shows a keyboard focus ring. */
export const ThePreviewOpensFromTheKeyboard: Story = {
  args: { file: { id: "pic-svg", filename: "logo.svg", content_type: "image/svg+xml" } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Preview logo.svg" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    await within(document.body).findByRole("dialog", { name: "logo.svg" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).toBeNull());
  },
};

/** A long unbroken file name does not widen the thumbnail's button or the dialog title. */
export const ALongFileNameKeepsTheButtonTheSameSize: Story = {
  args: { file: { id: "pic-png", filename: "Supercalifragilisticexpialidocious_Supercalifragilisticexpial.png", content_type: "image/png" } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: /^Preview Supercali/ });
    await expect(button.getBoundingClientRect().width).toBeLessThanOrEqual(48);
    await userEvent.click(button);
    const dialog = await within(document.body).findByRole("dialog");
    await expect(dialog.getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth);
    await userEvent.keyboard("{Escape}");
  },
};
