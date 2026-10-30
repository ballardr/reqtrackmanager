import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import type { ReportImageLibrary } from "../api/reportLayouts";
import { buildImageLibrary, buildReportImages } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportImageField } from "./ReportImageField";

function Host({ library, initial = "", scope = "project" }: { library: ReportImageLibrary; initial?: string; scope?: "organization" | "project" }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportImageField label="Image" value={value} library={library} scope={scope} onChange={setValue} required help="A picture from the library." />
      <output aria-label="Chosen">{value}</output>
    </>
  );
}

/** An image block's picture: its thumbnail and name, and a library dialog to pick, upload or delete a picture. */
const meta: Meta<typeof Host> = { title: "Components/ReportImageField", component: Host, args: { library: buildImageLibrary() } };
export default meta;

type Story = StoryObj<typeof Host>;

const dialog = () => screen.findByRole("dialog");

export const NoPictureChosenYetIsMarkedRequired: Story = {
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Image"]);
    await expect(within(canvasElement).getByText("No image chosen")).toBeInTheDocument();
    await expect(within(canvasElement).getByRole("button", { name: "Choose image…" })).toBeInTheDocument();
  },
};

/** Selecting a picture and pressing Use image stores its file id and closes the dialog (a double click does both). */
export const PickingAPictureFromTheLibrary: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await expect(await modal.findByText("site-logo.png")).toBeInTheDocument();
    await expect(modal.getByText("Used by 2 layouts")).toBeInTheDocument();
    await userEvent.click(modal.getByRole("button", { name: "Select organisation-wordmark.svg" }));
    await userEvent.click(modal.getByRole("button", { name: "Use image" }));
    await waitFor(() => expect(within(canvasElement).getByLabelText("Chosen")).toHaveTextContent("image-2"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await expect(within(canvasElement).getByText("organisation-wordmark.svg")).toBeInTheDocument();
  },
};

export const ASearchNarrowsTheLibraryByName: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await userEvent.type(await modal.findByRole("textbox", { name: "Search images" }), "wordmark");
    await expect(modal.queryByText("site-logo.png")).toBeNull();
    await userEvent.clear(modal.getByRole("textbox", { name: "Search images" }));
    await userEvent.type(modal.getByRole("textbox", { name: "Search images" }), "zzz");
    await expect(modal.getByText("No image matches your search.")).toBeInTheDocument();
  },
};

/** An empty library says what to upload. */
export const AnEmptyLibrary: Story = {
  args: { library: buildImageLibrary([]) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    await expect(await within(await dialog()).findByText(/No images yet/)).toBeInTheDocument();
  },
};

const many = Array.from({ length: 30 }, (_, i) => ({
  ...buildReportImages()[0], id: `image-${i}`, filename: `photo-${String(i).padStart(2, "0")}.jpg`, content_type: "image/jpeg", size_bytes: 500_000 + i * 90_000,
}));

/** A big library scrolls inside the dialog. */
export const ManyImages: Story = {
  args: { library: buildImageLibrary(many) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await expect(await modal.findByText("photo-29.jpg")).toBeInTheDocument();
    await expect(modal.getAllByRole("listitem")).toHaveLength(30);
  },
};

/** The limit is the deployment's setting, shown in the dialog and enforced before sending. */
export const TheDeploymentsSizeLimitIsShownAndUsed: Story = {
  args: { library: buildImageLibrary(buildReportImages(), 2 * 1024 * 1024) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await expect(await modal.findByText(/Largest file: 2 MB/)).toBeInTheDocument();
    const big = new File(["x"], "big.png", { type: "image/png" });
    Object.defineProperty(big, "size", { value: 3 * 1024 * 1024 });
    await userEvent.upload(screen.getByRole("dialog").querySelector<HTMLInputElement>('input[type="file"]')!, big);
    await expect(await modal.findByText("That file is too large (limit 2 MB).")).toBeInTheDocument();
    await expect(args.library.upload).not.toHaveBeenCalled();
  },
};

/** A selected photograph shows what the file records about itself, so photographs can be told apart without good names. */
export const ASelectedPhotographShowsItsMetadata: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await userEvent.click(await modal.findByRole("button", { name: "Select site-logo.png" }));
    const panel = within(await modal.findByLabelText("Image details"));
    await expect(await panel.findByText("4032 × 3024 px")).toBeInTheDocument();
    await expect(panel.getByText("2026-10-12 14:03:11")).toBeInTheDocument();
    await expect(panel.getByText("Canon EOS 5D")).toBeInTheDocument();
    await expect(panel.getByText("North gate, pump house")).toBeInTheDocument();
    await expect(panel.getByText("-33.86667, 151.21000")).toBeInTheDocument();
  },
};

/** A file with no metadata says so instead of showing an empty panel. */
export const AFileWithNoMetadataSaysSo: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await userEvent.click(await modal.findByRole("button", { name: "Select organisation-wordmark.svg" }));
    await expect(await within(await modal.findByLabelText("Image details")).findByText("This file records no camera details.")).toBeInTheDocument();
    await expect(modal.getByLabelText("Image details")).toHaveTextContent("Used by Quarterly review, Decision log.");
  },
};

/** Until something is selected the panel says what to do, and Use image is off. */
export const NothingSelectedYetPromptsAndDisablesUse: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await expect(await modal.findByText("Select a picture to see its details.")).toBeInTheDocument();
    await expect(modal.getByRole("button", { name: "Use image" })).toBeDisabled();
  },
};

/** The dialog says where an upload goes, because an organisation picture is visible to every project's layouts. */
export const AnUploadNamesItsDestination: Story = {
  args: { scope: "organization" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    await expect(await within(await dialog()).findByText(/Uploads go to the organisation's library/)).toBeInTheDocument();
  },
};

/** An upload is added to the library and announced; a file over the cap is refused before it is sent. */
export const AnUploadIsAddedAndATooLargeFileIsRefused: Story = {
  args: { library: buildImageLibrary() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await modal.findByText("site-logo.png");
    const input = screen.getByRole("dialog").querySelector<HTMLInputElement>('input[type="file"]')!;
    await userEvent.upload(input, new File(["x"], "new-photo.png", { type: "image/png" }));
    await expect((await modal.findAllByText("new-photo.png")).length).toBeGreaterThan(0);  // in the grid, and as the selection
    await expect(modal.getByRole("button", { name: "Select new-photo.png" })).toHaveAttribute("aria-pressed", "true");
    await expect(args.library.upload).toHaveBeenCalledTimes(1);

    const huge = new File(["x"], "huge.png", { type: "image/png" });
    Object.defineProperty(huge, "size", { value: 51 * 1024 * 1024 });
    await userEvent.upload(input, huge);
    await expect(await modal.findByText("That file is too large (limit 50 MB).")).toBeInTheDocument();
    await expect(args.library.upload).toHaveBeenCalledTimes(1);
  },
};

/** The server's refusal (a file that is not a picture) is shown in the dialog. */
export const AServerRefusalIsShown: Story = {
  args: { library: { ...buildImageLibrary(), upload: fn(async () => { throw new Error("Only PNG, JPEG, GIF, WebP and plain SVG images can be used in a report."); }) } },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await modal.findByText("site-logo.png");
    // The picker's accept list hides other files from the chooser, but a drag or a renamed file can still send one.
    await userEvent.setup({ applyAccept: false }).upload(
      screen.getByRole("dialog").querySelector<HTMLInputElement>('input[type="file"]')!, new File(["x"], "notes.txt", { type: "text/plain" }),
    );
    await expect(await modal.findByRole("alert")).toHaveTextContent("Only PNG, JPEG, GIF, WebP and plain SVG images");
  },
};

/** Only a picture the library owns can be deleted, behind a confirmation that names the layouts using it. */
export const DeletingAnOwnedPictureAsksFirst: Story = {
  args: { library: buildImageLibrary() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose image…" }));
    const modal = within(await dialog());
    await modal.findByText("site-logo.png");
    await expect(modal.queryByRole("button", { name: "Delete organisation-wordmark.svg" })).toBeNull();
    await userEvent.click(modal.getByRole("button", { name: "Delete site-logo.png" }));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(args.library.remove).toHaveBeenCalledWith("image-1"));
    await waitFor(() => expect(modal.queryByText("site-logo.png")).toBeNull());
  },
};

/** A block that names a picture which is no longer in the library says so. */
export const AMissingPictureIsReported: Story = {
  args: { initial: "image-gone" },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("This image is no longer in the library. Choose another.")).toBeInTheDocument();
  },
};

export const ShowsTheChosenPicture: Story = {
  args: { initial: "image-1" },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("site-logo.png")).toBeInTheDocument();
    await expect(within(canvasElement).getByRole("button", { name: "Change image…" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ShowsTheChosenPicture, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ShowsTheChosenPicture, globals: { theme: "dark" } };
