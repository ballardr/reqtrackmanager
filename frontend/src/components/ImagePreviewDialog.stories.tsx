import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { withPictureFiles } from "../testing/pictureFiles";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ImagePreviewDialog } from "./ImagePreviewDialog";

/** The larger view of a picture file, opened from a file list's thumbnail. */
const meta: Meta<typeof ImagePreviewDialog> = {
  title: "Components/ImagePreviewDialog",
  component: ImagePreviewDialog,
  args: { onClose: fn() },
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withPictureFiles],
};
export default meta;

type Story = StoryObj<typeof ImagePreviewDialog>;

async function dialogOf(name: string) {
  return within(document.body).findByRole("dialog", { name });
}

/** The picture is drawn on the shared backdrop inside the dialog, with the file name as title and a Download link. */
export const APictureOnItsBackdropWithDownload: Story = {
  args: { file: { id: "pic-png", filename: "logo.png", content_type: "image/png" } },
  play: async () => {
    const dialog = await dialogOf("logo.png");
    const picture = within(dialog).getByRole("img", { name: "logo.png" });
    await expect(picture.classList.contains("picture-backdrop")).toBe(true);
    const download = within(dialog).getByRole("link", { name: "Download" });
    await expect(download.getAttribute("download")).toBe("logo.png");
    await expect(download.getAttribute("href")).toContain("/api/v1/files/pic-png");
  },
};

/** An SVG has no natural size, so it is scaled to fill the dialog; it is still an image element, never inlined. */
export const AnSvgIsScaledToFit: Story = {
  args: { file: { id: "pic-svg", filename: "logo.svg", content_type: "image/svg+xml" } },
  play: async () => {
    const dialog = await dialogOf("logo.svg");
    const picture = within(dialog).getByRole("img", { name: "logo.svg" });
    await expect(picture.tagName).toBe("IMG");
    await expect(picture.classList.contains("image-preview--vector")).toBe(true);
    await expect(dialog.querySelector(".dialog-body svg")).toBeNull();
    await waitFor(() => expect(picture.getBoundingClientRect().width).toBeGreaterThan(200));
  },
};

/** A very wide picture is fitted to the dialog's width, never past it. */
export const AVeryWidePictureFits: Story = {
  args: { file: { id: "pic-wide", filename: "banner.png", content_type: "image/png" } },
  play: async () => {
    const dialog = await dialogOf("banner.png");
    const picture = within(dialog).getByRole<HTMLImageElement>("img", { name: "banner.png" });
    await waitFor(() => expect(picture.complete && picture.naturalWidth > 0).toBe(true));
    await expect(picture.getBoundingClientRect().width).toBeLessThanOrEqual(dialog.getBoundingClientRect().width);
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth);
  },
};

/** A very tall picture is fitted to the window's height, so the dialog never grows past the window. */
export const AVeryTallPictureFits: Story = {
  args: { file: { id: "pic-tall", filename: "poster.png", content_type: "image/png" } },
  play: async () => {
    const dialog = await dialogOf("poster.png");
    const picture = within(dialog).getByRole<HTMLImageElement>("img", { name: "poster.png" });
    await waitFor(() => expect(picture.complete && picture.naturalWidth > 0).toBe(true));
    await expect(picture.getBoundingClientRect().height).toBeLessThanOrEqual(window.innerHeight * 0.65 + 1);
    await expect(dialog.getBoundingClientRect().bottom).toBeLessThanOrEqual(window.innerHeight);
  },
};

/** A tiny raster is shown at its natural size, never upscaled to fill the dialog. */
export const ATinyPictureIsNotUpscaled: Story = {
  args: { file: { id: "pic-tiny", filename: "dot.png", content_type: "image/png" } },
  play: async () => {
    const dialog = await dialogOf("dot.png");
    const picture = within(dialog).getByRole<HTMLImageElement>("img", { name: "dot.png" });
    await waitFor(() => expect(picture.complete && picture.naturalWidth > 0).toBe(true));
    await expect(picture.getBoundingClientRect().width).toBeLessThanOrEqual(picture.naturalWidth);
  },
};

/** A transparent picture stays visible in the dark theme: the backdrop is drawn behind it. */
export const ATransparentPictureInTheDarkTheme: Story = {
  args: { file: { id: "pic-png", filename: "mark.png", content_type: "image/png" } },
  decorators: [
    (Story) => {
      document.documentElement.dataset.theme = "dark";
      return <Story />;
    },
  ],
  play: async () => {
    try {
      const dialog = await dialogOf("mark.png");
      const picture = within(dialog).getByRole("img", { name: "mark.png" });
      await expect(getComputedStyle(picture).backgroundImage).not.toBe("none");
    } finally {
      delete document.documentElement.dataset.theme;
    }
  },
};

/** A picture that cannot be loaded shows a message instead of an empty frame. */
export const AnUnreadablePictureShowsAMessage: Story = {
  args: { file: { id: "missing", filename: "gone.png", content_type: "image/png" } },
  play: async () => {
    const dialog = await dialogOf("gone.png");
    within(dialog).getByRole("img", { name: "gone.png" }).dispatchEvent(new Event("error"));
    await expect(await within(dialog).findByRole("alert")).toHaveTextContent("The picture could not be loaded.");
  },
};

/** The header close control and Escape both close the dialog. */
export const CloseControlAndEscapeClose: Story = {
  args: { file: { id: "pic-png", filename: "logo.png", content_type: "image/png" } },
  play: async ({ args }) => {
    const dialog = await dialogOf("logo.png");
    await userEvent.click(within(dialog).getByRole("button", { name: /close/i }));
    await waitFor(() => expect(args.onClose).toHaveBeenCalledTimes(1));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(args.onClose).toHaveBeenCalledTimes(2));
  },
};

/** A 200-character file name wraps in the title and does not push the dialog past the window. */
export const LongText: Story = {
  args: {
    file: {
      id: "pic-png", content_type: "image/png",
      filename: "An exceptionally long name that keeps going well past any sensible single line of text so that every control and column beside it is put under real pressure to stay where it belongs and not move at all.png",
    },
  },
  play: async () => {
    const dialog = await within(document.body).findByRole("dialog");
    await expect(dialog.getBoundingClientRect().right).toBeLessThanOrEqual(window.innerWidth);
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth);
    await expect(within(dialog).getByRole("link", { name: "Download" })).toBeVisible();
  },
};
