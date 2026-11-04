import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { ReportFontChoice } from "../api/reportLayouts";
import { STANDARD_FONT_CHOICES } from "../utils/reportFonts";
import { FontChoiceField } from "./FontChoiceField";

const EXTRA: ReportFontChoice = { key: "x-fira-sans", label: "Fira Sans", bundled: false, generic: "sans-serif" };

function Harness({ initial, fonts = [...STANDARD_FONT_CHOICES, EXTRA] }: { initial?: string; fonts?: ReportFontChoice[] }) {
  const [value, setValue] = useState<string | undefined>(initial);
  return (
    <>
      <FontChoiceField label="Font" value={value} onChange={(key) => setValue(key || undefined)} emptyLabel="Document font" fonts={fonts} help="The font of this block." />
      <output data-testid="value">{value ?? "none"}</output>
    </>
  );
}

/** The font select every report setting that names a font shares: the standard fonts, then the administrator's, behind an empty option. */
const meta: Meta<typeof Harness> = { title: "Components/FontChoiceField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const TheEmptyOptionSaysWhatIsInherited: Story = {
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: "Font" });
    await expect(select).toHaveValue("");
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Document font", "Sans", "Serif", "Mono", "Unicode Sans", "Fira Sans (provided by the server administrator)",
    ]);
  },
};

export const ChoosingAndClearingAFont: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Font" }), "serif");
    await expect(canvas.getByTestId("value")).toHaveTextContent("serif");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Font" }), "");
    await expect(canvas.getByTestId("value")).toHaveTextContent("none");
  },
};

export const AFontTheServerNoLongerOffersStaysVisible: Story = {
  args: { initial: "x-gone" },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: "Font" });
    await expect(select).toHaveValue("x-gone");
    await expect(within(select).getByRole("option", { name: "x-gone (not offered by this server)" })).toBeInTheDocument();
  },
};
