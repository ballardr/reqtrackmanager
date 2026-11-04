import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildColourContext } from "../testing/reportLayoutFixtures";
import type { TableHeadings } from "../utils/reportPageSetup";
import { TableHeadingColours } from "./TableHeadingColours";

function Harness({ initial = {}, disabled = false, problems }: { initial?: TableHeadings; disabled?: boolean; problems?: string[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <TableHeadingColours value={value} onChange={setValue} colours={buildColourContext()} disabled={disabled} problems={problems} />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

/** A layout's default table heading colours: a fill, a text colour and a sample heading row showing the result. */
const meta: Meta<typeof Harness> = { title: "Components/TableHeadingColours", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const heading = (canvas: ReturnType<typeof within>) => canvas.getByRole("columnheader", { name: "Code" });

export const UnsetShowsTheAccentWithContrastText: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(heading(canvas)).toHaveStyle({ backgroundColor: "rgb(15, 98, 254)", color: "rgb(255, 255, 255)" });
    await expect(canvas.getByRole("button", { name: "Table heading fill: Default (the organisation's accent)" })).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Table heading text: Automatic (black or white)" })).toBeVisible();
  },
};

export const ALightFillGetsBlackTextAndAnExplicitTextColourWins: Story = {
  args: { initial: { fill: "#ffe08a" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(heading(canvas)).toHaveStyle({ backgroundColor: "rgb(255, 224, 138)", color: "rgb(0, 0, 0)" });
    await userEvent.click(canvas.getByRole("button", { name: /^Table heading text: / }));
    await userEvent.click(within(document.body).getByRole("button", { name: /^White/ }));
    await expect(heading(canvas)).toHaveStyle({ color: "rgb(255, 255, 255)" });
    await expect(JSON.parse(canvas.getByTestId("value").textContent ?? "{}")).toEqual({ fill: "#ffe08a", text: "white" });
  },
};

export const OnlyATextColourKeepsTheAccentFill: Story = {
  args: { initial: { text: "black" } },
  play: async ({ canvasElement }) => {
    await expect(heading(within(canvasElement))).toHaveStyle({ backgroundColor: "rgb(15, 98, 254)", color: "rgb(0, 0, 0)" });
  },
};

export const NoColourIsNotOffered: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /^Table heading fill: / }));
    await expect(within(document.body).queryByRole("button", { name: /^No colour/ })).not.toBeInTheDocument();
    await expect(within(document.body).getByRole("button", { name: "Default (the organisation's accent)" })).toBeVisible();
  },
};

export const ReadOnlyAndWithAProblem: Story = {
  args: { initial: { fill: "#102030" }, disabled: true, problems: ["table_header_fill: Not a colour."] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: /^Table heading fill: / })).toBeDisabled();
    await expect(canvas.getByRole("alert")).toHaveTextContent("Not a colour.");
  },
};

export const LightTheme: Story = { ...ALightFillGetsBlackTextAndAnExplicitTextColourWins, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ALightFillGetsBlackTextAndAnExplicitTextColourWins, globals: { theme: "dark" } };
