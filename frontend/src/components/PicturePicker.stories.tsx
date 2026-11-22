import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { FileAsset } from "../api/types";
import { buildFileAsset } from "../testing/storybook-helpers";
import { MarkdownImageSourceProvider } from "./MarkdownImageSource";
import { PicturePickerPopover, PictureToolbarButton, type PictureChoice } from "./PicturePicker";

/** The picture panel (choose an attachment, upload one, give it words) and the toolbar button that opens it. */
const meta: Meta = { title: "Components/PicturePicker" };
export default meta;

type Story = StoryObj;

const PLOT = buildFileAsset({ id: "11111111-1111-4111-8111-111111111111", filename: "plot.png", content_type: "image/png" });
const SKETCH = buildFileAsset({ id: "22222222-2222-4222-8222-222222222222", filename: "sketch.svg", content_type: "image/svg+xml" });
const PAPER = buildFileAsset({ id: "33333333-3333-4333-8333-333333333333", filename: "paper.pdf", content_type: "application/pdf" });

/** The button inside a record page's picture source, beside a record of what the editor was asked to insert. */
function Harness({ files = [PLOT, SKETCH, PAPER], upload, withSource = true }: {
  files?: FileAsset[];
  upload?: (file: File) => Promise<FileAsset>;
  withSource?: boolean;
}) {
  const [last, setLast] = useState("");
  const button = <PictureToolbarButton onInsert={(choice: PictureChoice) => setLast(JSON.stringify(choice))} />;
  return (
    <>
      <div className="row">{withSource ? <MarkdownImageSourceProvider files={files} upload={upload}>{button}</MarkdownImageSourceProvider> : button}</div>
      <p data-testid="last">{last}</p>
    </>
  );
}

export const ChoosesARecordPictureAndGivesItWords: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Picture" }));
    // Only the pictures among the attachments are offered, never the PDF.
    await expect(await page.findByRole("button", { name: "Picture plot.png" })).toBeInTheDocument();
    await expect(page.getByRole("button", { name: "Picture sketch.svg" })).toBeInTheDocument();
    await expect(page.queryByRole("button", { name: "Picture paper.pdf" })).toBeNull();
    await userEvent.click(page.getByRole("button", { name: "Picture plot.png" }));
    await userEvent.type(await page.findByRole("textbox", { name: "Alternative text" }), "Throughput by hour");
    await userEvent.type(page.getByRole("textbox", { name: "Caption" }), "Figure 1");
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await expect(canvas.getByTestId("last")).toHaveTextContent(JSON.stringify({ fileId: PLOT.id, alt: "Throughput by hour", caption: "Figure 1" }));
    await waitFor(() => expect(page.queryByRole("textbox", { name: "Alternative text" })).toBeNull());
  },
};

export const AlternativeTextAndCaptionAreOptional: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Picture" }));
    await userEvent.click(await page.findByRole("button", { name: "Picture sketch.svg" }));
    await userEvent.click(await page.findByRole("button", { name: "Insert" }));
    await expect(canvas.getByTestId("last")).toHaveTextContent(JSON.stringify({ fileId: SKETCH.id, alt: "", caption: "" }));
  },
};

export const UploadsDuringTheInsertAndChoosesTheNewAttachment: Story = {
  render: () => {
    const fresh = buildFileAsset({ id: "44444444-4444-4444-8444-444444444444", filename: "new.png", content_type: "image/png" });
    return <Harness files={[]} upload={fn(async () => fresh)} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Picture" }));
    await expect(await page.findByText("No pictures are attached to this record yet.")).toBeInTheDocument();
    const input = document.body.querySelector('.picture-picker input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "new.png", { type: "image/png" }));
    // The upload is an ordinary attachment and is chosen at once: the next step is its words.
    await userEvent.type(await page.findByRole("textbox", { name: "Alternative text" }), "New");
    await userEvent.click(page.getByRole("button", { name: "Insert" }));
    await expect(canvas.getByTestId("last")).toHaveTextContent(JSON.stringify({ fileId: "44444444-4444-4444-8444-444444444444", alt: "New", caption: "" }));
  },
};

export const AFailedUploadIsExplainedAndNothingIsChosen: Story = {
  render: () => <Harness files={[]} upload={async () => { throw new Error("The file is too large."); }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Picture" }));
    const input = document.body.querySelector('.picture-picker input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "big.png", { type: "image/png" }));
    await expect(await page.findByRole("alert")).toHaveTextContent("The file is too large.");
    await expect(page.queryByRole("textbox", { name: "Alternative text" })).toBeNull();
  },
};

export const OffersNoUploadWhereAttachmentsCannotBeAdded: Story = {
  render: () => <Harness upload={undefined} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const page = within(document.body);
    await userEvent.click(canvas.getByRole("button", { name: "Picture" }));
    await expect(await page.findByText("Pictures cannot be added to this record now.")).toBeInTheDocument();
    await expect(document.body.querySelector('.picture-picker input[type="file"]')).toBeNull();
    await expect(page.getByRole("button", { name: "Picture plot.png" })).toBeInTheDocument();
  },
};

export const NoButtonWhereThereIsNoRecordToAttachTo: Story = {
  render: () => <Harness withSource={false} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Picture" })).toBeNull();
  },
};

/** Changing a picture already in the text keeps its file and asks only for its words. */
function ChangeHarness({ onApply }: { onApply: (choice: PictureChoice) => void }) {
  const anchor = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button ref={anchor} type="button" className="btn">The picture</button>
      <PicturePickerPopover
        anchorRef={anchor} source={{ files: [PLOT] }} initial={{ fileId: PLOT.id, alt: "Old words", caption: "" }}
        onApply={onApply} onClose={() => undefined}
      />
    </>
  );
}

export const ChangingAPictureKeepsItsFileAndAsksOnlyForItsWords: Story = {
  render: () => <ChangeHarness onApply={fn()} />,
  play: async () => {
    const page = within(document.body);
    const alt = await page.findByRole("textbox", { name: "Alternative text" });
    await expect(alt).toHaveValue("Old words");
    await expect(page.queryByRole("button", { name: "Back" })).toBeNull();
    await userEvent.clear(alt);
    await userEvent.type(alt, "New words");
    await userEvent.click(page.getByRole("button", { name: "Apply" }));
  },
};
