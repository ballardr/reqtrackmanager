import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, within } from "storybook/test";

import type { FileDetails } from "../api/fileDetails";
import { FileDetailsToggle } from "./FileDetailsPanel";

const PHOTO: FileDetails = {
  width_px: 4032, height_px: 3024, taken: "2026-10-12 14:03:11", camera: "Canon EOS 5D", description: "North gate, pump house",
  latitude: -33.866667, longitude: 151.21,
};
const NONE: FileDetails = { width_px: 640, height_px: 480, taken: null, camera: null, description: null, latitude: null, longitude: null };

/** An info button beside a file's name that shows what a picture says about itself; nothing for a file that is not a picture. */
const meta: Meta<typeof FileDetailsToggle> = {
  title: "Components/FileDetailsToggle",
  component: FileDetailsToggle,
  args: { file: { id: "f1", filename: "gate.jpg", content_type: "image/jpeg" }, load: fn(async () => PHOTO) },
};
export default meta;

type Story = StoryObj<typeof FileDetailsToggle>;

export const AShowsAPhotographsMetadata: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Details of gate.jpg" }));
    const popover = within(await screen.findByRole("dialog"));
    await expect(await popover.findByText("4032 × 3024 px")).toBeInTheDocument();
    await expect(popover.getByText("2026-10-12 14:03:11")).toBeInTheDocument();
    await expect(popover.getByText("Canon EOS 5D")).toBeInTheDocument();
    await expect(popover.getByText("North gate, pump house")).toBeInTheDocument();
    await expect(popover.getByText("-33.86667, 151.21000")).toBeInTheDocument();
    await expect(args.load).toHaveBeenCalledWith("f1");
  },
};

/** The details are read when first opened, not for every row of a list. */
export const BDetailsAreReadOnlyWhenOpened: Story = {
  play: async ({ canvasElement, args }) => {
    await expect(args.load).not.toHaveBeenCalled();
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Details of gate.jpg" }));
    await screen.findByRole("dialog");
    await expect(args.load).toHaveBeenCalledTimes(1);
  },
};

export const CAPictureWithNoMetadataSaysSo: Story = {
  args: { load: fn(async () => NONE) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Details of gate.jpg" }));
    const popover = within(await screen.findByRole("dialog"));
    await expect(await popover.findByText("640 × 480 px")).toBeInTheDocument();
    await expect(popover.getByText("This file records no camera details.")).toBeInTheDocument();
  },
};

export const DAFailureIsReported: Story = {
  args: { load: fn(async () => { throw new Error("no"); }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Details of gate.jpg" }));
    await expect(await within(await screen.findByRole("dialog")).findByRole("alert")).toHaveTextContent("The details could not be read.");
  },
};

/** A picture is recognised by its name when the declared type says nothing; any other file has no button. */
export const EOnlyPicturesGetTheButton: Story = {
  render: (args) => (
    <div className="row">
      <FileDetailsToggle {...args} file={{ id: "a", filename: "photo.PNG", content_type: "application/octet-stream" }} />
      <FileDetailsToggle {...args} file={{ id: "c", filename: "logo.svg", content_type: "image/svg+xml" }} />
      <FileDetailsToggle {...args} file={{ id: "b", filename: "spec.pdf", content_type: "application/pdf" }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Details of photo.PNG" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Details of logo.svg" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Details of spec.pdf" })).toBeNull();
  },
};

export const LightTheme: Story = { ...AShowsAPhotographsMetadata, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AShowsAPhotographsMetadata, globals: { theme: "dark" } };
