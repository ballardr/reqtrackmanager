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

/** Every module starts collapsed; opening a module shows its reports, collapsed too, and opening one lists its parts. */
export const ListsPartsAsACollapsedTreeOfModulesAndReports: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Expand Risk Management" })).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.getByRole("button", { name: "Expand Decision Management" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Risk register" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Expand Risk Management" }));
    await expect(canvas.queryByRole("button", { name: "Headline figures" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Expand Risk register" }));
    await expect(canvas.getByRole("button", { name: "Risk register" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Headline figures" })).toBeInTheDocument();
    await expect(canvas.getByText("Table")).toBeInTheDocument();
    await expect(canvas.getByText("Figures")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Collapse Risk Management" }));
    await expect(canvas.queryByRole("button", { name: "Headline figures" })).not.toBeInTheDocument();
  },
};

/** The module name is said once for its three reports, instead of in front of each. */
export const SaysTheModuleOnceForItsReports: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Expand Decision Management" }));
    await expect(canvas.getByRole("button", { name: "Expand Decision register" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Expand Approval ageing" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Expand Decision log" })).toBeInTheDocument();
    await expect(canvas.queryByText(/Decision Management ·/)).not.toBeInTheDocument();
  },
};

/** Settings are written bare for numbers and booleans and quoted for text; an unset one is left out. */
export const InsertsTheLineWithItsSettings: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Expand Risk Management" }));
    await userEvent.click(canvas.getByRole("button", { name: "Expand Risk register" }));
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

/** Searching by a module's name opens it, and the reports under it, without a click. */
export const SearchingByModuleOpensItsBranches: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Find a widget" }), "decision management");
    await expect(canvas.getByRole("button", { name: "Decision register" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Decision log" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Risk register" })).not.toBeInTheDocument();
  },
};

export const NoWidgetsSaysSo: Story = {
  args: { widgets: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No report parts are available to this layout.")).toBeInTheDocument();
  },
};
