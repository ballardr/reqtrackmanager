import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { UploadsDisabledPrompt } from "./UploadsDisabledPrompt";

const meta: Meta<typeof UploadsDisabledPrompt> = {
  title: "Components/UploadsDisabledPrompt",
  component: UploadsDisabledPrompt,
  args: { info: { fileCount: 12, fileBytes: 5 * 1024 * 1024, reason: "deployment" }, onCancel: fn(), onContinue: fn() },
};
export default meta;

type Story = StoryObj<typeof UploadsDisabledPrompt>;

/** States how many files (and how much data) cannot be stored and offers exactly two actions. */
export const CancelOrContinue: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("12 files (5.0 MB) cannot be stored because file uploads are disabled on this deployment.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Import without files" }));
    await expect(args.onContinue).toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Cancel import" }));
    await expect(args.onCancel).toHaveBeenCalled();
  },
};

export const SingleFile: Story = {
  args: { info: { fileCount: 1, fileBytes: 100, reason: "deployment" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/^1 file \(100 B\) cannot be stored/)).toBeInTheDocument();
  },
};

/** While the repeated request runs both actions are unavailable. */
export const Busy: Story = {
  args: { busy: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Import without files" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Cancel import" })).toBeDisabled();
  },
};

export const LightTheme: Story = { ...CancelOrContinue, globals: { theme: "light" } };
export const DarkTheme: Story = { ...CancelOrContinue, globals: { theme: "dark" } };

/** When the organisation's own switch stops the files the sentence says so. */
export const OrganisationSwitch: Story = {
  args: { info: { fileCount: 2, fileBytes: 2048, reason: "organization" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("2 files (2.0 KB) cannot be stored because file uploads are disabled for this organisation.")).toBeInTheDocument();
  },
};

/** When the storage limit would be exceeded the sentence gives the size and the space left, with the same two actions. */
export const StorageLimit: Story = {
  args: { info: { fileCount: 3, fileBytes: 5 * 1024 * 1024, reason: "quota", remainingBytes: 1024 * 1024 } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("3 files (5.0 MB) do not fit in the storage space left for this organisation (1.0 MB).")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Import without files" }));
    await expect(args.onContinue).toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Cancel import" }));
    await expect(args.onCancel).toHaveBeenCalled();
  },
};
