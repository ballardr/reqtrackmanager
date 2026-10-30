import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildImageLibrary } from "../testing/reportLayoutFixtures";
import type { RunningBand } from "../utils/reportPageSetup";
import { RunningBandEditor } from "./RunningBandEditor";

/** Hosts the editor with the band it edits, and shows the band as JSON so a story can read what was written. */
function Host({
  initial, kind = "header", inheritFrom = "template", margin = 1.5, withImages = false, disabled = false,
}: {
  initial?: RunningBand;
  kind?: "header" | "footer";
  inheritFrom?: "template" | "layout";
  margin?: number;
  withImages?: boolean;
  disabled?: boolean;
}) {
  const [value, setValue] = useState<RunningBand | undefined>(initial);
  return (
    <div className="stack">
      <RunningBandEditor
        kind={kind} value={value} onChange={setValue} inheritFrom={inheritFrom} margin={margin} disabled={disabled}
        images={withImages ? { library: buildImageLibrary(), scope: "project" } : undefined}
      />
      <pre aria-label="Band">{JSON.stringify(value ?? null)}</pre>
    </div>
  );
}

/** One header or footer: a row of left, centre and right cells with an optional logo, inherited, its own or empty. */
const meta: Meta<typeof RunningBandEditor> = { title: "Components/RunningBandEditor", component: RunningBandEditor };
export default meta;

type Story = StoryObj<typeof RunningBandEditor>;

const band = (canvasElement: HTMLElement) => JSON.parse(within(canvasElement).getByLabelText("Band").textContent ?? "null");

/** Nothing is set, so it inherits; choosing its own text shows three cells and typing writes them. */
export const OwnTextFillsTheThreeCells: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(view.getByRole("combobox", { name: "Header: print" })).toHaveValue("inherit");
    await expect(view.queryByRole("textbox", { name: "Header, left cell" })).toBeNull();
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: print" }), "custom");
    await userEvent.type(view.getByRole("textbox", { name: "Header, centre cell" }), "{{{{report_title}}");
    await userEvent.type(view.getByRole("textbox", { name: "Header, right cell" }), "Page {{{{page}}");
    await expect(band(canvasElement)).toEqual({ left: "", centre: "{{report_title}}", right: "Page {{page}}" });
  },
};

/** A placeholder is added to the end of the cell edited last. */
export const InsertingAPlaceholderGoesToTheLastCell: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.type(view.getByRole("textbox", { name: "Footer, right cell" }), "Page ");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Insert placeholder" }), "page");
    await expect(band(canvasElement).right).toBe("Page {{page}}");
  },
};

/** "Nothing" is an empty band, which prints no header at all; "inherit" removes the band again. */
export const NothingIsAnEmptyBandAndInheritRemovesIt: Story = {
  render: () => <Host initial={{ left: "x" }} inheritFrom="layout" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: print" }), "none");
    await expect(band(canvasElement)).toEqual({});
    await expect(view.queryByRole("textbox", { name: "Header, left cell" })).toBeNull();
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: print" }), "inherit");
    await expect(band(canvasElement)).toBeNull();
    await expect(view.getByRole("option", { name: "Same as the layout's" })).toBeInTheDocument();
  },
};

/** The first page can be skipped, for a cover page. */
export const TheFirstPageCanBeSkipped: Story = {
  render: () => <Host initial={{ left: "Cover-less" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: first page" }), "none");
    await expect(band(canvasElement).first_page).toBe("none");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: first page" }), "same");
    await expect(band(canvasElement).first_page).toBeUndefined();
  },
};

/** A logo taller than the margin allows is reported with the margin it needs, before the save is refused. */
export const ALogoTooTallForTheMarginIsWarnedAbout: Story = {
  render: () => <Host initial={{ left: "A", logo: { file: "image-1", height: 2 } }} withImages />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByRole("alert")).toHaveTextContent("The header needs a top margin of at least 2.5 cm; it is 1.5 cm.");
    const height = view.getByRole("spinbutton", { name: "Logo height (cm)" });
    await userEvent.clear(height);
    await userEvent.type(height, "0.8");
    await expect(view.queryByRole("alert")).toBeNull();
    await expect(view.getByText("The header takes 1.3 cm of the margin.")).toBeInTheDocument();
  },
};

/** Removing the logo keeps the band (with an empty left cell) rather than turning it into "nothing". */
export const RemovingTheLogoKeepsTheBand: Story = {
  render: () => <Host initial={{ logo: { file: "image-1", height: 1 } }} withImages />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.click(await view.findByRole("button", { name: "Remove logo (header)" }));
    await expect(band(canvasElement)).toEqual({ left: "" });
  },
};

/** Read-only: the cells show their text and cannot be edited. */
export const ReadOnly: Story = {
  render: () => <Host initial={{ left: "Fixed" }} disabled />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("textbox", { name: "Header, left cell" })).toBeDisabled();
  },
};
