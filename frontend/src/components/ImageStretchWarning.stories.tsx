import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, waitFor, within } from "storybook/test";

import { buildImageLibrary } from "../testing/reportLayoutFixtures";
import { ImageStretchWarning } from "./ImageStretchWarning";

const library = buildImageLibrary();

/** The note under an image block's size when Width and Height are both set to a ratio unlike the picture's (image-1 is 4032 x 3024, 4:3). */
const meta: Meta<typeof ImageStretchWarning> = {
  title: "Components/ImageStretchWarning",
  component: ImageStretchWarning,
  args: { library },
};
export default meta;

type Story = StoryObj<typeof ImageStretchWarning>;

export const AMatchingRatioSaysNothing: Story = {
  args: { node: { type: "image", file: "image-1", width: 8, height: 6 } },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(library.details).toHaveBeenCalledWith("image-1"));
    await new Promise((resolve) => setTimeout(resolve, 50)); // let the details land before asserting nothing appeared
    await expect(within(canvasElement).queryByRole("status")).not.toBeInTheDocument();
  },
};

export const AStretchedPictureIsWarnedAbout: Story = {
  args: { node: { type: "image", file: "image-1", width: 8, height: 2, height_unit: "cm" } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("status")).toHaveTextContent("4.00:1 (width to height) but the picture is 1.33:1");
  },
};

export const MillimetresAreComparedAsLengths: Story = {
  args: { node: { type: "image", file: "image-1", width: 80, width_unit: "mm", height: 2, height_unit: "cm" } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("status")).toHaveTextContent("4.00:1 (width to height)");
  },
};

export const OneAutoDimensionKeepsTheRatioAndSaysNothing: Story = {
  args: { node: { type: "image", file: "image-1", width: 8 } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("status")).not.toBeInTheDocument();
  },
};

export const APercentageWidthIsNotJudged: Story = {
  args: { node: { type: "image", file: "image-1", width: 50, width_unit: "percent", height: 2 } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("status")).not.toBeInTheDocument();
  },
};
