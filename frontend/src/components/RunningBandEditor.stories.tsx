import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildImageLibrary } from "../testing/reportLayoutFixtures";
import type { RunningBand } from "../utils/reportPageSetup";
import { RunningBandEditor } from "./RunningBandEditor";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";

/** Hosts the editor with the band it edits, and shows the band as JSON so a story can read what was written. */
function Host({
  initial, kind = "header", inheritFrom = "template", margin = 1.5, withImages = false, disabled = false, placeholders,
}: {
  /** The list the designer passes: the server's catalogue, which names no page field. */
  placeholders?: readonly string[];
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
        kind={kind} value={value} onChange={setValue} inheritFrom={inheritFrom} margin={margin} disabled={disabled} placeholders={placeholders}
        images={withImages ? { library: buildImageLibrary(), scope: "project" } : undefined}
      />
      <pre aria-label="Band">{JSON.stringify(value ?? null)}</pre>
    </div>
  );
}

/** One header or footer: a row of left, centre and right cells with an optional logo, inherited, its own or empty. */
const meta: Meta<typeof RunningBandEditor> = { title: "Components/RunningBandEditor", component: RunningBandEditor, decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))] };
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

/** The designer passes the server's catalogue, which has no page fields; the editor still offers them, in plain words. */
export const PageFieldsAreOfferedWhateverTheCatalogueHolds: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" placeholders={["project_name", "report_title"]} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const insert = view.getByRole("combobox", { name: "Insert placeholder" });
    await expect(within(insert).getByRole("option", { name: "Page number ({{page}})" })).toBeInTheDocument();
    await expect(within(insert).getByRole("option", { name: "Total pages ({{pages}})" })).toBeInTheDocument();
    await userEvent.selectOptions(insert, "page_of_pages");
    await expect(band(canvasElement).left).toBe("Page {{page}} of {{pages}}");
    await expect(view.getByText("Page 3 of 12")).toBeInTheDocument();
    await expect(view.getByText("Page 3 of 12").parentElement).toHaveTextContent("Prints as: Page 3 of 12");
  },
};

/** A placeholder is written where the caret is, not at the end. */
export const InsertingWritesAtTheCaret: Story = {
  render: () => <Host initial={{ left: "Report  draft" }} kind="footer" placeholders={[]} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const cell = view.getByRole("textbox", { name: "Footer, left cell" }) as HTMLTextAreaElement;
    await userEvent.click(cell);
    cell.setSelectionRange(7, 7);
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Insert placeholder" }), "page");
    await expect(band(canvasElement).left).toBe("Report {{page}} draft");
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

/** Font, size and colour are set for the whole band, and each setting is removed again when emptied. */
export const FontSizeAndColourApplyToTheWholeBand: Story = {
  render: () => <Host initial={{ left: "A" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Footer: font" }), "serif");
    const size = view.getByRole("spinbutton", { name: "Footer: size (pt)" });
    await userEvent.type(size, "10");
    await expect(band(canvasElement)).toEqual({ left: "A", font: "serif", size: 10 });
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Footer: font" }), "");
    await userEvent.clear(size);
    await expect(band(canvasElement)).toEqual({ left: "A" });
  },
};

/** The Bold and Italic buttons wrap the selected words of the cell last edited in the marks the server reads. */
export const BoldAndItalicWrapTheSelection: Story = {
  render: () => <Host initial={{ centre: "Draft copy" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const cell = view.getByRole("textbox", { name: "Footer, centre cell" }) as HTMLTextAreaElement;
    cell.focus();
    cell.setSelectionRange(0, 5);
    await userEvent.click(view.getByRole("button", { name: "Footer: Bold" }));
    await expect(band(canvasElement).centre).toBe("**Draft** copy");
    cell.focus();
    cell.setSelectionRange(10, 14);
    await userEvent.click(view.getByRole("button", { name: "Footer: Italic" }));
    await expect(band(canvasElement).centre).toBe("**Draft** *copy*");
  },
};

/** With nothing selected a mark pair is written, so typing continues inside it. */
export const NothingSelectedWritesAMarkPair: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.click(view.getByRole("textbox", { name: "Footer, left cell" }));
    await userEvent.click(view.getByRole("button", { name: "Footer: Bold" }));
    await expect(band(canvasElement).left).toBe("****");
  },
};

/** The sample under a cell shows its marks, drawn in the band's own colour. */
export const TheSampleShowsTheMarks: Story = {
  render: () => <Host initial={{ right: "**Page {{page}}** of {{pages}}", colour: "#ff0000" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const bold = view.getByText("Page 3");
    await expect(bold).toHaveStyle("font-weight: 700");
    await expect(bold.parentElement).toHaveTextContent("Prints as: Page 3 of 12");
  },
};

/** A taller line (a larger size) needs a taller margin, and the editor says so before the save is refused. */
export const ALargerSizeNeedsATallerMargin: Story = {
  render: () => <Host initial={{ left: "a\nb\nc", size: 24 }} kind="footer" margin={1.5} />,
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The footer needs a bottom margin of at least");
  },
};

/** A cell fits its text unless given a width; clearing the field removes the width again. */
export const ACellWidthIsOptional: Story = {
  render: () => <Host initial={{ left: "Ballard", centre: "Title" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const width = view.getByRole("textbox", { name: "Left width" });
    await expect(width).toHaveValue("");
    await userEvent.type(width, "25%");
    await expect(band(canvasElement).left_width).toBe("25%");
    await userEvent.clear(width);
    await expect(band(canvasElement).left_width).toBeUndefined();
  },
};

/** The band sits cells at the top unless told otherwise, and a cell's own choice is written beside its text. */
export const CellsAreTopAlignedUnlessChosen: Story = {
  render: () => <Host initial={{ left: "Ballard", centre: "Title" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(view.getByRole("combobox", { name: "Header: vertical alignment" })).toHaveValue("top");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Left vertical alignment" }), "bottom");
    await expect(band(canvasElement).left_valign).toBe("bottom");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: vertical alignment" }), "middle");
    await expect(band(canvasElement).valign).toBe("middle");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Left vertical alignment" }), "");
    await expect(band(canvasElement).left_valign).toBeUndefined();
  },
};
