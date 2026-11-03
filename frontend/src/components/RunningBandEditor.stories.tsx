import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

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

/** Opens the band's "More" group (closed until opened), as a person would. */
const openMore = async (view: ReturnType<typeof within>, kind: "Header" | "Footer") => {
  const bar = view.getByRole("button", { name: `More ${kind.toLowerCase()} options section` });
  if (bar.getAttribute("aria-expanded") !== "true") await userEvent.click(bar);
};

/** Opens a cell's settings popover. */
const openCell = async (view: ReturnType<typeof within>, cell: "Left" | "Centre" | "Right") => {
  await userEvent.click(view.getByRole("button", { name: new RegExp(`^${cell} cell settings`) }));
  return within(await within(document.body).findByRole("dialog"));
};

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

/** Opens a cell's [+] placeholder menu and returns it. */
const openPlaceholders = async (view: ReturnType<typeof within>, kind: "Header" | "Footer", cell: "left" | "centre" | "right") => {
  await userEvent.click(view.getByRole("button", { name: `Insert placeholder into ${kind.toLowerCase()}, ${cell} cell` }));
  return within(await within(document.body).findByRole("menu"));
};

/** A cell's [+] writes the placeholder into that cell only, at its end when it has not been clicked in. */
export const InsertingAPlaceholderGoesToThatCell: Story = {
  render: () => <Host initial={{ left: "Keep" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.type(view.getByRole("textbox", { name: "Footer, right cell" }), "Page ");
    await userEvent.click(await (await openPlaceholders(view, "Footer", "right")).findByRole("menuitem", { name: /^Page number/ }));
    await expect(band(canvasElement).right).toBe("Page {{page}}");
    await expect(band(canvasElement).left).toBe("Keep");
    // The menu closes and the caret is back in the cell, after the placeholder.
    await waitFor(() => expect(view.getByRole("textbox", { name: "Footer, right cell" })).toHaveFocus());
    await expect(within(document.body).queryByRole("menu")).toBeNull();
  },
};

/** The menu is short and grouped: the page fields, then report, project and organisation values, each with a sample; no old drop-down remains. */
export const ThePlaceholderMenuIsGroupedWithSamples: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" placeholders={["project_name", "report_title", "organisation", "layout_version", "odd_name"]} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(view.queryByRole("combobox", { name: "Insert placeholder" })).toBeNull();
    const menu = await openPlaceholders(view, "Footer", "left");
    await expect(menu.getAllByRole("menuitem").map((item) => item.textContent?.split(" ")[0])).toHaveLength(8);
    for (const heading of ["Page", "Report", "Project", "Organisation", "Other"]) await expect(menu.getByText(heading)).toBeInTheDocument();
    await expect(menu.getByRole("menuitem", { name: /^Project name\s*Apollo/ })).toBeInTheDocument();
    await userEvent.click(menu.getByRole("menuitem", { name: /^\{\{odd_name\}\}/ }));
    await expect(band(canvasElement).left).toBe("{{odd_name}}");
  },
};

/** Escape closes the menu and puts focus back on the [+]. */
export const EscapeClosesThePlaceholderMenuOnItsButton: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await openPlaceholders(view, "Footer", "left");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(within(document.body).queryByRole("menu")).toBeNull());
    await expect(view.getByRole("button", { name: "Insert placeholder into footer, left cell" })).toHaveFocus();
  },
};

/** The designer passes the server's catalogue, which has no page fields; the editor still offers them, in plain words. */
export const PageFieldsAreOfferedWhateverTheCatalogueHolds: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" placeholders={["project_name", "report_title"]} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const menu = await openPlaceholders(view, "Footer", "left");
    await expect(menu.getByRole("menuitem", { name: /^Page number \(\{\{page\}\}\)/ })).toBeInTheDocument();
    await expect(menu.getByRole("menuitem", { name: /^Total pages \(\{\{pages\}\}\)/ })).toBeInTheDocument();
    await userEvent.click(menu.getByRole("menuitem", { name: /^Page X of Y/ }));
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
    await userEvent.click(await (await openPlaceholders(view, "Footer", "left")).findByRole("menuitem", { name: /^Page number/ }));
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
    await openMore(view, "Header");
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
    // The fit message is outside the closed "More" group, where the logo's height is.
    await expect(await view.findByRole("alert")).toHaveTextContent("The header needs a top margin of at least 2.5 cm; it is 1.5 cm.");
    await openMore(view, "Header");
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
    await openMore(view, "Header");
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
    await openMore(view, "Footer");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Footer: font" }), "serif");
    const size = view.getByRole("spinbutton", { name: "Footer: size (pt)" });
    await userEvent.type(size, "10");
    await expect(band(canvasElement)).toEqual({ left: "A", font: "serif", size: 10 });
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Footer: font" }), "");
    await userEvent.clear(size);
    await expect(band(canvasElement)).toEqual({ left: "A" });
  },
};

/** A cell's Bold and Italic buttons wrap that cell's selected words in the marks the server reads. */
export const BoldAndItalicWrapTheSelection: Story = {
  render: () => <Host initial={{ centre: "Draft copy" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const cell = view.getByRole("textbox", { name: "Footer, centre cell" }) as HTMLTextAreaElement;
    cell.focus();
    cell.setSelectionRange(0, 5);
    await userEvent.click(view.getByRole("button", { name: "Footer, centre cell: Bold" }));
    await expect(band(canvasElement).centre).toBe("**Draft** copy");
    cell.focus();
    cell.setSelectionRange(10, 14);
    await userEvent.click(view.getByRole("button", { name: "Footer, centre cell: Italic" }));
    await expect(band(canvasElement).centre).toBe("**Draft** *copy*");
  },
};

/** With nothing selected a mark pair is written, so typing continues inside it. */
export const NothingSelectedWritesAMarkPair: Story = {
  render: () => <Host initial={{ left: "" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.click(view.getByRole("textbox", { name: "Footer, left cell" }));
    await userEvent.click(view.getByRole("button", { name: "Footer, left cell: Bold" }));
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

/** A cell fits its text unless given a width (set in the cell's settings popover); clearing the field removes the width again. */
export const ACellWidthIsOptional: Story = {
  render: () => <Host initial={{ left: "Ballard", centre: "Title" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const popover = await openCell(view, "Left");
    const width = popover.getByRole("textbox", { name: "Left width" });
    await expect(width).toHaveValue("");
    await userEvent.type(width, "25%");
    await expect(band(canvasElement).left_width).toBe("25%");
    await userEvent.clear(width);
    await expect(band(canvasElement).left_width).toBeUndefined();
  },
};

/** A footer sits its cells at the bottom unless told otherwise: the default is marked, and choosing "Top" is stored because it is not the default. */
export const FooterCellsAreBottomAlignedUnlessChosen: Story = {
  render: () => <Host kind="footer" initial={{ left: "Ballard", centre: "Title" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await openMore(view, "Footer");
    const select = view.getByRole("combobox", { name: "Footer: vertical alignment" });
    await expect(select).toHaveValue("bottom");
    await expect(within(select).getByRole("option", { name: "Bottom (default)" })).toBeInTheDocument();
    await userEvent.selectOptions(select, "top");
    await expect(band(canvasElement).valign).toBe("top");
    await userEvent.selectOptions(select, "bottom");
    await expect(band(canvasElement).valign).toBeUndefined();
  },
};

/** The band sits cells at the top unless told otherwise, and a cell's own choice (set in its popover) is written beside its text. */
export const CellsAreTopAlignedUnlessChosen: Story = {
  render: () => <Host initial={{ left: "Ballard", centre: "Title" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await openMore(view, "Header");
    await expect(view.getByRole("combobox", { name: "Header: vertical alignment" })).toHaveValue("top");
    const popover = await openCell(view, "Left");
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Left vertical alignment" }), "bottom");
    await expect(band(canvasElement).left_valign).toBe("bottom");
    await userEvent.selectOptions(view.getByRole("combobox", { name: "Header: vertical alignment" }), "middle");
    await expect(band(canvasElement).valign).toBe("middle");
    // Choosing in the band's own select (outside the popover) closes the popover; the cell's gear opens it again.
    const reopened = await openCell(view, "Left");
    await userEvent.selectOptions(reopened.getByRole("combobox", { name: "Left vertical alignment" }), "");
    await expect(band(canvasElement).left_valign).toBeUndefined();
  },
};

/** The three cells sit one above the other, left then centre then right, each as wide as the editor. */
export const TheCellsAreStackedLeftCentreRight: Story = {
  render: () => <Host initial={{ left: "L", centre: "C", right: "R" }} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const boxes = ["left", "centre", "right"].map((cell) => view.getByRole("textbox", { name: `Header, ${cell} cell` }));
    const rects = boxes.map((box) => box.getBoundingClientRect());
    await expect(rects[0].bottom).toBeLessThanOrEqual(rects[1].top);
    await expect(rects[1].bottom).toBeLessThanOrEqual(rects[2].top);
    await expect(Math.abs(rects[0].left - rects[2].left)).toBeLessThan(1);
    await expect(Math.abs(rects[0].width - rects[2].width)).toBeLessThan(1);
  },
};

/** A cell's gear opens a popover, Escape closes it with focus back on the gear; a width and alignment set there show beside the title and mark the gear. */
export const ACellsSettingsPopoverClosesOnEscapeAndIsSummarised: Story = {
  render: () => <Host initial={{ left: "A", right_width: "6 cm", right_valign: "bottom" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const gear = view.getByRole("button", { name: "Right cell settings: width 6 cm, bottom" });
    await expect(gear).toHaveClass("btn-marked");
    await expect(view.getByText("width 6 cm, bottom")).toBeInTheDocument();
    await expect(view.getByRole("button", { name: "Left cell settings" })).not.toHaveClass("btn-marked");
    await userEvent.click(gear);
    await expect(await within(document.body).findByRole("dialog", { name: "Right cell settings" })).toBeInTheDocument();
    await expect(gear).toHaveAttribute("aria-expanded", "true");
    // Focus opens on the first field's help (?), whose tip takes the first Escape; the second closes the popover.
    await userEvent.keyboard("{Escape}{Escape}");
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(gear).toHaveFocus());
  },
};

/** "More" starts closed; its bar counts what is set, and the fit message stays outside it. */
export const MoreStartsClosedAndCountsWhatIsSet: Story = {
  render: () => <Host initial={{ left: "A", font: "serif", size: 10, first_page: "none" }} kind="footer" />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const bar = view.getByRole("button", { name: "More footer options section" });
    await expect(bar).toHaveAttribute("aria-expanded", "false");
    await expect(view.getByText("3 changed")).toBeInTheDocument();
    await expect(view.queryByRole("combobox", { name: "Footer: font" })).toBeNull();
    await expect(view.getByText(/^The footer takes [\d.]+ cm of the margin\.$/)).toBeInTheDocument();
    await userEvent.click(bar);
    await expect(view.getByRole("combobox", { name: "Footer: font" })).toHaveValue("serif");
  },
};
