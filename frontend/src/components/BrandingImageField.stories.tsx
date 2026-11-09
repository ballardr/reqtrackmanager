import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildUser, withAuth } from "../testing/storybook-helpers";
import { BrandingImageField } from "./BrandingImageField";

const meta: Meta<typeof BrandingImageField> = {
  title: "Components/BrandingImageField",
  component: BrandingImageField,
  decorators: [withAuth(buildUser())],
  args: {
    id: "logo-input", label: "Default logo", fileId: null, platformFileId: null, busy: false, height: 40,
    onSelect: fn(), onRemove: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof BrandingImageField>;

/** No file of its own and no platform picture: only the upload control. */
export const Empty: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Default logo")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove" })).toBeNull();
    await expect(canvas.queryByText("Platform default")).toBeNull();
  },
};

/** With no file of its own the platform picture is shown muted under a caption, and there is nothing to remove. */
export const ShowsThePlatformPicture: Story = {
  args: { platformFileId: "platform-logo" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Platform default")).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "Remove" })).toBeNull();
  },
};

/** The organisation's own file has a Remove button, and no "Custom" pill. */
export const OwnFileCanBeRemoved: Story = {
  args: { fileId: "own-logo", platformFileId: "platform-logo" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Custom")).toBeNull();
    await expect(canvas.queryByText("Platform default")).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Remove" }));
    await expect(args.onRemove).toHaveBeenCalledOnce();
  },
};

/** Messages from the upload show beside the control; the controls are unavailable while busy. */
export const BusyWithMessages: Story = {
  args: { fileId: "own-logo", busy: true, error: "The file is too large.", uploaded: "Logo uploaded." },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("alert")).toHaveTextContent("The file is too large.");
    await expect(canvas.getByText("Logo uploaded.")).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Remove" })).toBeDisabled();
  },
};
