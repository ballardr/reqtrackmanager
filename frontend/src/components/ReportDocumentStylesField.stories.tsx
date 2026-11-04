import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { ReportFontChoice } from "../api/reportLayouts";
import { buildColourContext } from "../testing/reportLayoutFixtures";
import type { ColourEntry } from "../utils/reportColours";
import { STANDARD_FONT_CHOICES, type DocumentStyles } from "../utils/reportFonts";
import { ReportDocumentStylesField } from "./ReportDocumentStylesField";

const EXTRA: ReportFontChoice = { key: "x-fira-sans", label: "Fira Sans", bundled: false, generic: "sans-serif" };
const OWN: ColourEntry[] = [{ name: "warning", colour: "#b45309" }];

function Harness({
  initial, fonts = [...STANDARD_FONT_CHOICES, EXTRA], disabled = false,
}: { initial?: DocumentStyles; fonts?: ReportFontChoice[]; disabled?: boolean }) {
  const [value, setValue] = useState<DocumentStyles | undefined>(initial);
  return (
    <>
      <ReportDocumentStylesField
        label="Fonts" value={value} onChange={setValue} fonts={fonts} colours={buildColourContext()} palette={OWN} disabled={disabled}
      />
      <output data-testid="value">{JSON.stringify(value ?? null)}</output>
    </>
  );
}

/** The document's body and heading fonts, set once for the whole layout (the tree's `styles`). */
const meta: Meta<typeof Harness> = { title: "Components/ReportDocumentStylesField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const stored = (canvasElement: HTMLElement) => JSON.parse(within(canvasElement).getByTestId("value").textContent ?? "null");

export const NothingSetLeavesEveryFormatItsOwnLook: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Body font" })).toHaveValue("");
    await expect(canvas.getByRole("combobox", { name: "Heading font" })).toHaveValue("");
    await expect(canvas.getByRole("checkbox", { name: "Bold headings" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Italic headings" })).not.toBeChecked();
    await expect(stored(canvasElement)).toBeNull();
  },
};

export const TheStandardFontsComeFirstThenThoseTheAdministratorProvides: Story = {
  play: async ({ canvasElement }) => {
    const labels = within(within(canvasElement).getByRole("combobox", { name: "Body font" })).getAllByRole("option").map((o) => o.textContent);
    await expect(labels).toEqual([
      "Default (each format's own font)", "Sans", "Serif", "Mono", "Unicode Sans", "Fira Sans (provided by the server administrator)",
    ]);
  },
};

export const ChoosingFontsAndASizeStoresOnlyWhatWasSet: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Body font" }), "serif");
    await userEvent.type(canvas.getByRole("spinbutton", { name: "Body size (pt)" }), "11.5");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Heading font" }), "x-fira-sans");
    await waitFor(() => expect(stored(canvasElement)).toEqual({ body: { font: "serif", size: 11.5 }, headings: { font: "x-fira-sans" } }));
  },
};

export const SwitchesStoreWhatDiffersFromTheDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: "Bold headings" }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Italic headings" }));
    await waitFor(() => expect(stored(canvasElement)).toEqual({ headings: { bold: false, italic: true } }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Bold headings" }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Italic headings" }));
    await waitFor(() => expect(stored(canvasElement)).toBeNull()); // nothing set is no key at all, never an empty object
  },
};

export const TheHeadingColourIsChosenFromTheSchemeByName: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Heading colour: Default (each format's own colour)" }));
    await userEvent.click(within(document.body).getByRole("button", { name: /^warning/ }));
    await waitFor(() => expect(stored(canvasElement)).toEqual({ headings: { colour: "warning" } }));
  },
};

export const ClearingTheLastSettingRemovesTheValue: Story = {
  args: { initial: { body: { font: "serif" } } },
  play: async ({ canvasElement }) => {
    await userEvent.selectOptions(within(canvasElement).getByRole("combobox", { name: "Body font" }), "");
    await waitFor(() => expect(stored(canvasElement)).toBeNull());
  },
};

export const AFontTheServerNoLongerOffersIsKeptAndSaysSo: Story = {
  args: { initial: { body: { font: "x-gone" } } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Body font" })).toHaveValue("x-gone");
    await expect(canvas.getByText(/This server does not offer the font x-gone/)).toBeVisible();
    await expect(stored(canvasElement)).toEqual({ body: { font: "x-gone" } });
  },
};

export const ReadOnlyShowsTheValuesWithoutControlsToChangeThem: Story = {
  args: { initial: { body: { font: "serif", size: 11 } }, disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Body font" })).toBeDisabled();
    await expect(canvas.getByRole("spinbutton", { name: "Body size (pt)" })).toHaveValue(11);
    await expect(canvas.getByRole("checkbox", { name: "Bold headings" })).toBeDisabled();
  },
};
