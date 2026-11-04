import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildColourContext } from "../testing/reportLayoutFixtures";
import type { ColourEntry } from "../utils/reportColours";
import { ColourChoiceField } from "./ColourChoiceField";

const OWN: ColourEntry[] = [{ name: "warning", colour: "#b45309" }, { name: "alert", colour: "#7a0000" }];

function Harness({
  initial = "accent", emptyLabel, allowNone = true, allowNames = true, disabled = false, palette = OWN,
}: { initial?: string; emptyLabel?: string; allowNone?: boolean; allowNames?: boolean; disabled?: boolean; palette?: ColourEntry[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ColourChoiceField
        helpNotNeeded label="Fill" value={value} onChange={setValue} context={buildColourContext()} layoutPalette={palette}
        emptyLabel={emptyLabel} allowNone={allowNone} allowNames={allowNames} disabled={disabled}
      />
      <output data-testid="value">{value}</output>
    </>
  );
}

/** The one colour control of a report layout: the branding colour, the layout's scheme, the organisation's, then fixed words. */
const meta: Meta<typeof Harness> = { title: "Components/ColourChoiceField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

export const TheButtonNamesTheColourAndShowsItsHex: Story = {
  args: { initial: "warning" },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Fill: warning" });
    await expect(button).toHaveTextContent("#b45309");
  },
};

export const TheBrandingColourIsFirstWithItsActualColour: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" }));
    const popover = within(document.body);
    const lines = popover.getAllByRole("button", { pressed: true });
    await expect(lines[0]).toHaveTextContent("Branding colour");
    await expect(lines[0]).toHaveTextContent("#0f62fe");
  },
};

export const TheListGroupsTheLayoutsColoursThenTheOrganisationsThenTheStandardFour: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" }));
    const body = within(document.body);
    const headings = ["Branding", "This layout's colours", "The organisation's colours", "Standard colours", "Other"];
    for (const name of headings) await expect(body.getByRole("group", { name })).toBeVisible();
    const own = within(body.getByRole("group", { name: "This layout's colours" }));
    await expect(own.getAllByRole("button").map((b) => b.textContent)).toEqual(["warning#b45309", "alert#7a0000"]);
    // The organisation's "alert" is overridden by the layout's own, so only "success" is left in its group.
    await expect(within(body.getByRole("group", { name: "The organisation's colours" })).getAllByRole("button")).toHaveLength(1);
    await expect(within(body.getByRole("group", { name: "Standard colours" })).getAllByRole("button")).toHaveLength(4);
  },
};

export const ChoosingASchemeNameKeepsTheNameNotTheHex: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" }));
    await userEvent.click(within(document.body).getByRole("button", { name: /^warning/ }));
    await waitFor(() => expect(within(canvasElement).getByTestId("value")).toHaveTextContent("warning"));
    await expect(within(document.body).queryByRole("group", { name: "Branding" })).not.toBeInTheDocument(); // the popover closed
  },
};

export const ACustomHexIsReportedAsItIsTypedAndKeepsTheListOpen: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" }));
    const box = within(document.body).getByRole("textbox", { name: "Fill (Custom colour) (hex code)" });
    await userEvent.clear(box);
    await userEvent.type(box, "#123abc");
    await waitFor(() => expect(within(canvasElement).getByTestId("value")).toHaveTextContent("#123abc"));
    await expect(within(document.body).getByRole("group", { name: "Branding" })).toBeVisible();
  },
};

export const NoColourIsAChoiceOnlyWhereTheFieldAllowsIt: Story = {
  args: { allowNone: false },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" }));
    await expect(within(document.body).queryByRole("button", { name: /^No colour/ })).not.toBeInTheDocument();
  },
};

export const AnUnsetFieldSaysWhatUnsetMeansAndCanBeCleared: Story = {
  args: { initial: "primary", emptyLabel: "No outline" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: primary" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "No outline" }));
    await waitFor(() => expect(within(canvasElement).getByRole("button", { name: "Fill: No outline" })).toBeVisible());
    await expect(within(canvasElement).getByTestId("value")).toHaveTextContent("");
  },
};

export const AnUnknownNameStillShowsAColourAndItsName: Story = {
  args: { initial: "ghost" },
  play: async ({ canvasElement }) => {
    // It resolves to the branding colour, as the server does, so the swatch is never blank.
    await expect(within(canvasElement).getByRole("button", { name: "Fill: ghost" })).toHaveTextContent("#0f62fe");
  },
};

export const ReadOnlyDisablesTheButton: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" })).toBeDisabled();
  },
};

export const WithoutNamesOnlyColoursAreOffered: Story = {
  args: { allowNames: false },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fill: Branding colour" }));
    const body = within(document.body);
    await expect(body.queryByRole("group", { name: "This layout's colours" })).not.toBeInTheDocument();
    await expect(body.queryByRole("group", { name: "Standard colours" })).not.toBeInTheDocument();
  },
};
