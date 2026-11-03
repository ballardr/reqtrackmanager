import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportLayoutPageSetup } from "./ReportLayoutPageSetup";

/** Hosts the control with the text it edits, and shows the text so a story can read the rewritten lines. */
function Host({ initial }: { initial: string }) {
  const [text, setText] = useState(initial);
  return (
    <div className="stack">
      <ReportLayoutPageSetup text={text} onChange={setText} />
      <pre aria-label="Text">{text}</pre>
    </div>
  );
}

/** Paper, orientation, margins, mirrored margins and page styles, written into the layout text's header lines. */
const meta: Meta<typeof ReportLayoutPageSetup> = {
  title: "Components/ReportLayoutPageSetup",
  component: ReportLayoutPageSetup,
  decorators: [withStatefulAuth(buildUser())],
  render: () => <Host initial={"@layout document\n\n@heading Hello\n"} />,
};
export default meta;

type Story = StoryObj<typeof ReportLayoutPageSetup>;

const text = (canvasElement: HTMLElement) => within(canvasElement).getByLabelText("Text");
const openDialog = async (canvasElement: HTMLElement, name: string) => {
  await userEvent.click(within(canvasElement).getByRole("button", { name }));
  return within(await screen.findByRole("dialog", { name: "Page setup" }));
};

/** Opens a closed setting group by its bar (a group that is already open is left alone). */
const openGroup = async (dialog: ReturnType<typeof within>, name: string) => {
  const bar = dialog.getByRole("button", { name: `${name} section` });
  if (bar.getAttribute("aria-expanded") !== "true") await userEvent.click(bar);
};

/** The button says the current setup, and a change rewrites only the first line. */
export const ChoosingASizeAndOrientationRewritesTheHeader: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A3");
    await expect(text(canvasElement).textContent).toBe("@layout document A3\n\n@heading Hello\n");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Orientation" }), "landscape");
    await expect(text(canvasElement).textContent).toBe("@layout document landscape A3\n\n@heading Hello\n");
    await expect(within(canvasElement).getByRole("button", { name: "Page setup: A3, landscape" })).toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A4");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Orientation" }), "portrait");
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** Margins and mirroring are written on the header line, and an emptied side is dropped again. */
export const MarginsAndMirroringAreWrittenOnTheHeader: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Top" }), "2");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Gutter" }), "1");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Mirror margins" }));
    await expect(text(canvasElement).textContent).toBe("@layout document mirror margins top=2 gutter=1\n\n@heading Hello\n");
    await expect(dialog.getByRole("spinbutton", { name: "Left (inner)" })).toBeInTheDocument();
    await userEvent.clear(dialog.getByRole("spinbutton", { name: "Top" }));
    await userEvent.clear(dialog.getByRole("spinbutton", { name: "Gutter" }));
    await userEvent.click(dialog.getByRole("checkbox", { name: "Mirror margins" }));
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** A page style is added, named and given its own paper; it is written as a `@pagestyle` line after the header. */
export const AddingAPageStyleWritesAPagestyleLine: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await openGroup(dialog, "Page styles");
    await userEvent.click(dialog.getByRole("button", { name: "Add page style" }));
    const name = dialog.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Wide tables");
    const group = within(dialog.getByRole("group", { name: "Wide tables" }));
    await userEvent.selectOptions(group.getByRole("combobox", { name: "Page size" }), "A3");
    await userEvent.selectOptions(group.getByRole("combobox", { name: "Orientation" }), "landscape");
    await userEvent.type(group.getByRole("spinbutton", { name: "Left" }), "1");
    await expect(text(canvasElement).textContent).toBe(
      '@layout document\n@pagestyle "Wide tables" landscape A3 margins left=1\n\n@heading Hello\n',
    );
    await userEvent.click(dialog.getByRole("button", { name: "Remove page style Wide tables" }));
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** A layout that already names a setup shows it, in either word order, with its page styles. */
export const ReadsTheSetupFromTheHeaderLines: Story = {
  render: () => <Host initial={'@layout document Letter landscape mirror margins top=2\n@pagestyle "Plain"\n'} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: Letter, landscape");
    await openGroup(dialog, "Page styles");
    // The layout's own fields come first, then each page style's.
    await expect(dialog.getAllByRole("combobox", { name: "Page size" })[0]).toHaveValue("Letter");
    await expect(dialog.getAllByRole("spinbutton", { name: "Top" })[0]).toHaveValue(2);
    await expect(dialog.getByRole("group", { name: "Plain" })).toBeInTheDocument();
  },
};

/** A table layout has no pages, so there is nothing to set. */
export const ATableLayoutHasNoPageSetup: Story = {
  render: () => <Host initial={"@layout table\n"} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: /^Page setup/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ReadsTheSetupFromTheHeaderLines, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ReadsTheSetupFromTheHeaderLines, globals: { theme: "dark" } };

/** A layout's header and footer are written as `@header` / `@footer` lines under the header line, and a page style's under its own. */
export const HeaderAndFooterAreWrittenUnderTheirOwnLines: Story = {
  render: () => <Host initial={'@layout document\n@pagestyle "Wide" A3\n\n@heading Hello\n'} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await openGroup(dialog, "Page styles");
    const header = within(dialog.getAllByRole("group", { name: "Header" })[0]); // the layout's own, above the page styles'
    await userEvent.selectOptions(header.getByRole("combobox", { name: "Header: print" }), "custom");
    await userEvent.type(header.getByRole("textbox", { name: "Header, centre cell" }), "{{{{report_title}}");
    const style = within(dialog.getByRole("group", { name: "Wide" }));
    await userEvent.selectOptions(style.getByRole("combobox", { name: "Footer: print" }), "none");
    await expect(text(canvasElement).textContent).toBe(
      '@layout document\n@header left "" centre "{{report_title}}"\n@pagestyle "Wide" A3\n@footer\n\n@heading Hello\n',
    );
  },
};

/** A layout that already has bands shows them, including a logo and a skipped first page, and a rewrite keeps them. */
export const ReadsHeadersAndFootersFromTheText: Story = {
  render: () => (
    <Host initial={'@layout document margins top=2\n@header left "A" logo "image-1" height 0.8 slot right first none\n@footer\n\n@heading Hello\n'} />
  ),
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    const header = within(dialog.getByRole("group", { name: "Header" }));
    await expect(header.getByRole("textbox", { name: "Header, left cell" })).toHaveValue("A");
    await userEvent.click(header.getByRole("button", { name: "More header options section" }));
    await expect(header.getByRole("combobox", { name: "Header: first page" })).toHaveValue("none");
    await expect(within(dialog.getByRole("group", { name: "Footer" })).getByRole("combobox", { name: "Footer: print" })).toHaveValue("none");
    await userEvent.type(header.getByRole("textbox", { name: "Header, left cell" }), "B");
    await expect(text(canvasElement).textContent).toBe(
      '@layout document margins top=2\n@header left "AB" logo "image-1" height 0.8 slot right first none\n@footer\n\n@heading Hello\n',
    );
  },
};

/** The alignment switch is written as `noalign`, kept when the rest of the setup is rewritten, and dropped when switched back on. */
export const TheAlignTablesSwitchIsWrittenAsAWordAndKept: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await openGroup(dialog, "Tables");
    const box = dialog.getByRole("checkbox", { name: "Line up tables with the same columns" });
    await expect(box).toBeChecked();
    await userEvent.click(box);
    await expect(text(canvasElement).textContent).toBe("@layout document noalign\n\n@heading Hello\n");
    await expect(within(canvasElement).getByRole("button", { name: "Page setup: A4, portrait" })).toHaveClass("btn-marked");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Repeat table header rows" }));
    await expect(text(canvasElement).textContent).toBe("@layout document norepeatheader noalign\n\n@heading Hello\n");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Repeat table header rows" }));
    await userEvent.click(box);
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** The heading-row switch is written on the header line as a word, kept when the rest of the setup is rewritten, and dropped when switched back on. */
export const TheRepeatHeaderSwitchIsWrittenAsAWordAndKept: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await openGroup(dialog, "Tables");
    const box = dialog.getByRole("checkbox", { name: "Repeat table header rows" });
    await expect(box).toBeChecked();
    await userEvent.click(box);
    await expect(text(canvasElement).textContent).toBe("@layout document norepeatheader\n\n@heading Hello\n");
    await expect(within(canvasElement).getByRole("button", { name: "Page setup: A4, portrait" })).toHaveClass("btn-marked");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A3");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Mirror margins" }));
    await expect(text(canvasElement).textContent).toBe("@layout document A3 mirror norepeatheader\n\n@heading Hello\n");
    await userEvent.click(dialog.getByRole("checkbox", { name: "Mirror margins" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A4");
    await userEvent.click(box);
    await expect(text(canvasElement).textContent).toBe("@layout document\n\n@heading Hello\n");
  },
};

/** A layout that already says `repeatheader` explicitly keeps the word until the switch is turned off. */
export const AnExplicitRepeatHeaderWordIsPreserved: Story = {
  render: () => <Host initial={"@layout document repeatheader\n\n@heading Hello\n"} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await openGroup(dialog, "Tables");
    await expect(dialog.getByRole("checkbox", { name: "Repeat table header rows" })).toBeChecked();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A3");
    await expect(text(canvasElement).textContent).toBe("@layout document A3 repeatheader\n\n@heading Hello\n");
  },
};

/** The run-scope word on the header line is not this dialog's setting, but rewriting the page setup keeps it. */
export const TheRunScopeWordIsKeptWhenThePageSetupIsRewritten: Story = {
  render: () => <Host initial={"@layout document projecttree\n\n@heading Hello\n"} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A3");
    await expect(text(canvasElement).textContent).toBe("@layout document A3 projecttree\n\n@heading Hello\n");
  },
};

/** The embed-fonts word on the header line (set under Fonts, not in this dialog) survives a rewrite of the line. */
export const TheEmbedFontsWordIsKeptWhenThePageSetupIsRewritten: Story = {
  render: () => <Host initial={"@layout document embedfonts\n\n@heading Hello\n"} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Page size" }), "A3");
    await expect(text(canvasElement).textContent).toBe("@layout document A3 embedfonts\n\n@heading Hello\n");
  },
};

/** Only the basic set and the header and footer start open; a closed group holding a change says so on its bar. */
export const ClosedGroupsMarkWhatTheyHold: Story = {
  render: () => <Host initial={'@layout document norepeatheader\n@pagestyle "Wide" A3\n@pagestyle "Narrow"\n\n@heading Hello\n'} />,
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    await expect(dialog.getByRole("combobox", { name: "Page size" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Header and footer section" })).toHaveAttribute("aria-expanded", "true");
    const tables = dialog.getByRole("button", { name: "Tables section" });
    await expect(tables).toHaveAttribute("aria-expanded", "false");
    await expect(tables).toHaveAccessibleDescription("1 changed");
    await expect(dialog.getByRole("button", { name: "Page styles section" })).toHaveAccessibleDescription("2 page styles");
    await expect(dialog.queryByRole("checkbox", { name: "Repeat table header rows" })).not.toBeInTheDocument();
  },
};

/** A group opens and closes from the keyboard, and the choice is remembered when the dialog is reopened. */
export const AGroupOpensByKeyboardAndStaysOpen: Story = {
  play: async ({ canvasElement }) => {
    const dialog = await openDialog(canvasElement, "Page setup: A4, portrait");
    const bar = dialog.getByRole("button", { name: "Tables section" });
    bar.focus();
    await userEvent.keyboard("{Enter}");
    await expect(dialog.getByRole("checkbox", { name: "Repeat table header rows" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Tables section" })).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    const again = await openDialog(canvasElement, "Page setup: A4, portrait");
    await expect(again.getByRole("checkbox", { name: "Repeat table header rows" })).toBeVisible();
    again.getByRole("button", { name: "Tables section" }).focus();
    await userEvent.keyboard(" ");
    await expect(again.queryByRole("checkbox", { name: "Repeat table header rows" })).not.toBeInTheDocument();
  },
};
