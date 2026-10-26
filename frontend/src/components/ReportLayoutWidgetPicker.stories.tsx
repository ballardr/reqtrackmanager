import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildWidgets } from "../testing/reportLayoutFixtures";
import { ReportLayoutWidgetPicker } from "./ReportLayoutWidgetPicker";

/** The widget picker of the layout designer: report parts to embed, with the report's settings. */
const meta: Meta<typeof ReportLayoutWidgetPicker> = {
  title: "Components/ReportLayoutWidgetPicker",
  component: ReportLayoutWidgetPicker,
  args: { widgets: buildWidgets(), onInsert: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportLayoutWidgetPicker>;

export const ListsPartsGroupedByReport: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const group = canvas.getByRole("region", { name: "Risk Management · Risk register" });
    await expect(within(group).getByRole("button", { name: "Risk register" })).toBeInTheDocument();
    await expect(within(group).getByRole("button", { name: "Headline figures" })).toBeInTheDocument();
    await expect(within(group).getByText("Table")).toBeInTheDocument();
    await expect(within(group).getByText("Figures")).toBeInTheDocument();
  },
};

/** Settings are written bare for numbers and booleans and quoted for text; an unset one is left out. */
export const InsertsTheLineWithItsSettings: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Risk register" }));
    const settings = within(canvas.getByRole("group", { name: "Settings" }));
    await expect(settings.getByLabelText("Inserts:")).toHaveTextContent("[[widget.risk_management.risk-register.register]]");
    await userEvent.clear(settings.getByRole("spinbutton", { name: "Lowest rating" }));
    await userEvent.type(settings.getByRole("spinbutton", { name: "Lowest rating" }), "9");
    await userEvent.type(settings.getByRole("textbox", { name: "Owner" }), "Ada Lovelace");
    await expect(settings.getByLabelText("Inserts:")).toHaveTextContent(
      '[[widget.risk_management.risk-register.register min_rating=9 owner="Ada Lovelace"]]',
    );
    await userEvent.click(settings.getByRole("button", { name: "Insert widget" }));
    await expect(args.onInsert).toHaveBeenCalledWith('[[widget.risk_management.risk-register.register min_rating=9 owner="Ada Lovelace"]]');
  },
};

export const FilteringNarrowsTheList: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a widget" }), "figures");
    await expect(canvas.queryByRole("button", { name: "Risk register" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Headline figures" })).toBeInTheDocument();
    await userEvent.clear(canvas.getByRole("textbox", { name: "Find a widget" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a widget" }), "nothing like it");
    await expect(canvas.getByText("No widget matches.")).toBeInTheDocument();
  },
};

export const NoWidgetsSaysSo: Story = {
  args: { widgets: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No report parts are available to this layout.")).toBeInTheDocument();
  },
};
