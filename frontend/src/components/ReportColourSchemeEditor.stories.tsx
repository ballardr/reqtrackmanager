import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildColourContext } from "../testing/reportLayoutFixtures";
import type { ColourEntry } from "../utils/reportColours";
import { ReportColourSchemeEditor } from "./ReportColourSchemeEditor";

function Harness({
  initial = [], mode = "layout", used = [], disabled = false,
}: { initial?: ColourEntry[]; mode?: "layout" | "organization"; used?: string[]; disabled?: boolean }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportColourSchemeEditor mode={mode} value={value} onChange={setValue} context={buildColourContext()} used={new Set(used)} disabled={disabled} />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
    </>
  );
}

/** A colour scheme: named colours blocks use by name. A layout's own, or the organisation's. */
const meta: Meta<typeof Harness> = { title: "Components/ReportColourSchemeEditor", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const read = (canvas: ReturnType<typeof within>): ColourEntry[] => JSON.parse(canvas.getByTestId("value").textContent ?? "[]");
const TWO: ColourEntry[] = [{ name: "primary", colour: "#1f3a5f" }, { name: "warning", colour: "#b45309" }];

export const ALayoutWithNoColoursSaysItFollowsTheOrganisation: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/no colours of its own/)).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "Follow the organisation's colours" })).not.toBeInTheDocument();
  },
};

export const AddingAColourOpensItsSettingsAtOnce: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add colour" }));
    await waitFor(() => expect(read(canvas)).toEqual([{ name: "colour1", colour: "accent" }]));
    await expect(within(document.body).getByRole("textbox", { name: "Name" })).toHaveValue("colour1");
  },
};

export const ARowShowsItsNameAndTheColourItResolvesTo: Story = {
  args: { initial: [{ name: "primary", colour: "accent" }] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("list", { name: "Colours in the scheme" })).toHaveTextContent("primary #0f62fe");
  },
};

export const RenamingAndRecolouringApplyAsTheyAreMade: Story = {
  args: { initial: TWO },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Colour settings: warning" }));
    const name = within(document.body).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "caution");
    await userEvent.click(within(document.body).getByRole("button", { name: /^Black/ }));
    await waitFor(() => expect(read(canvas)[1]).toEqual({ name: "caution", colour: "black" }));
  },
};

export const ANameThatIsNotValidIsFlaggedAsTyped: Story = {
  args: { initial: TWO },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Colour settings: warning" }));
    const name = within(document.body).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Bad Name");
    await expect(within(document.body).getByRole("alert")).toHaveTextContent("lower-case letters");
    await userEvent.clear(name);
    await userEvent.type(name, "primary");
    await expect(within(document.body).getByRole("alert")).toHaveTextContent("Another colour has this name");
  },
};

export const ARemovedColourGoesAndAUsedOneIsRefusedWithTheReason: Story = {
  args: { initial: TWO, used: ["primary"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Remove colour primary" }));
    await expect(canvas.getByRole("alert")).toHaveTextContent("primary is used by a block");
    await expect(read(canvas)).toHaveLength(2);
    await userEvent.click(canvas.getByRole("button", { name: "Remove colour warning" }));
    await waitFor(() => expect(read(canvas)).toEqual([TWO[0]]));
  },
};

export const AUsedNameCannotBeRenamed: Story = {
  args: { initial: TWO, used: ["primary"] },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Colour settings: primary" }));
    await expect(within(document.body).getByRole("textbox", { name: "Name" })).toBeDisabled();
  },
};

export const StartFromFillsTheListAndKeepsUsedNamesTheSetLacks: Story = {
  args: { initial: [{ name: "warning", colour: "#b45309" }], used: ["warning"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Start from" }), "cool");
    await waitFor(() => expect(read(canvas).map((e) => e.name)).toEqual(["primary", "secondary", "tint", "neutral", "warning"]));
  },
};

export const StartFromOffersTheOrganisationsColoursWhenItHasSome: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Start from" }), "organisation");
    await waitFor(() => expect(read(canvas)).toEqual([{ name: "alert", colour: "#b42318" }, { name: "success", colour: "#067647" }]));
  },
};

export const FollowingTheOrganisationClearsTheLayoutsOwnColours: Story = {
  args: { initial: TWO },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Follow the organisation's colours" }));
    await waitFor(() => expect(read(canvas)).toEqual([]));
  },
};

export const FollowingIsRefusedWhileABlockUsesAColourOnlyTheLayoutHas: Story = {
  args: { initial: TWO, used: ["warning"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Follow the organisation's colours" }));
    await expect(canvas.getByRole("alert")).toHaveTextContent("warning is used by a block");
    await expect(read(canvas)).toHaveLength(2);
  },
};

export const FollowingIsAllowedWhenTheUsedNameIsAStandardOne: Story = {
  args: { initial: TWO, used: ["primary"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Follow the organisation's colours" }));
    await waitFor(() => expect(read(canvas)).toEqual([]));
  },
};

export const AtMostEightColours: Story = {
  args: { initial: Array.from({ length: 8 }, (_, i) => ({ name: `c${i}`, colour: "#000000" })) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Add colour" })).toBeDisabled();
    await expect(canvas.getByText("A scheme holds at most 8 colours.")).toBeVisible();
  },
};

export const TheOrganisationsSchemeHasNoStartFromOrFollow: Story = {
  args: { mode: "organization", initial: TWO },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("combobox", { name: "Start from" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Follow the organisation's colours" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/A layout's own colour of the same name wins/)).toBeVisible();
  },
};

export const ReadOnlyShowsTheColoursWithoutEditing: Story = {
  args: { initial: TWO, disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Add colour" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove colour primary" })).not.toBeInTheDocument();
  },
};
