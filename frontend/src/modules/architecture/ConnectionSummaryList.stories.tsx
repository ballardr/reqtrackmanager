import { Pencil } from "lucide-react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { IconAction } from "../../components/IconAction";
import { orphanedControlViolations } from "../../testing/orphanedControls";
import { withRouter } from "../../testing/storybook-helpers";
import { buildConnection } from "./architectureFixtures";
import { ConnectionSummaryList } from "./ConnectionSummaryList";

const MANY = Array.from({ length: 12 }, (_, i) => buildConnection({
  id: `con-${i + 1}`, unique_code: `CON-${String(i + 1).padStart(3, "0")}`, name: `Link ${i + 1}`,
}));

const meta: Meta<typeof ConnectionSummaryList> = {
  title: "Modules/Architecture/ConnectionSummaryList",
  component: ConnectionSummaryList,
  decorators: [withRouter("/")],
  args: {
    label: "Connections of this line",
    connections: [buildConnection(), buildConnection({ id: "con-2", unique_code: "CON-002", name: "Admin traffic", connection_type_name: "gRPC", protocol: "" })],
    codeOf: (c) => c.unique_code,
    linkTo: (c) => `/connections/${c.id}`,
    actionsOf: (c) => <IconAction label={`Edit ${c.unique_code}`} onClick={fn()}><Pencil /></IconAction>,
  },
  // The Selection card's narrowest width (the stacked layout of a phone-sized editor).
  render: (args) => <div style={{ width: 240 }}><ConnectionSummaryList {...args} /></div>,
};
export default meta;

type Story = StoryObj<typeof ConnectionSummaryList>;

/** Each row reads code, type and protocol on one line and the two ends on the next, with the Edit action at its end. */
export const OneRowHasTheCodeAndTypeThenTheEnds: Story = {
  args: { connections: [buildConnection()] },
  play: async ({ canvasElement }) => {
    const list = within(canvasElement).getByRole("list", { name: "Connections of this line" });
    const row = within(list).getByRole("listitem");
    await expect(within(row).getByRole("link", { name: "CON-001" })).toHaveAttribute("href", "/connections/con-1");
    await expect(row).toHaveTextContent("REST API · HTTPS/1.1");
    await expect(row).toHaveTextContent("Gateway");
    await expect(row).toHaveTextContent("Orders");
    await expect(within(row).getByRole("button", { name: "Edit CON-001" })).toBeInTheDocument();
  },
};

export const TwoRowsFitTheNarrowCard: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("listitem")).toHaveLength(2);
    const list = canvasElement.querySelector<HTMLElement>(".item-row-list")!;
    await expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth + 1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

export const TwelveRowsStayAFlatList: Story = {
  args: { connections: MANY },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("listitem")).toHaveLength(12);
    const list = canvasElement.querySelector<HTMLElement>(".item-row-list")!;
    await expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth + 1);
  },
};

/** A long type, protocol and element names wrap as text; the code stays on one line and the Edit action stays beside the row. */
export const LongTypeProtocolAndNamesWrapWithoutBreakingTheCode: Story = {
  args: {
    connections: [buildConnection({
      unique_code: "F3ID-CON-003", connection_type_name: "Message queue with guaranteed ordered delivery",
      protocol: "AMQP 1.0 over TLS 1.3 with mutual authentication",
      source_element_name: "Telemetry ingestion gateway for the northern region",
      target_element_name: "Long-term archive of normalised telemetry records",
    })],
  },
  play: async ({ canvasElement }) => {
    const list = canvasElement.querySelector<HTMLElement>(".item-row-list")!;
    await expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth + 1);
    const code = within(canvasElement).getByRole("link", { name: "F3ID-CON-003" });
    // One line: the code's box is no taller than a single line of text.
    await expect(code.getBoundingClientRect().height).toBeLessThan(parseFloat(getComputedStyle(code).lineHeight) * 1.6);
    const edit = within(canvasElement).getByRole("button", { name: "Edit F3ID-CON-003" });
    await expect(edit.getBoundingClientRect().right).toBeLessThanOrEqual(list.getBoundingClientRect().right + 1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** A connection the viewer cannot edit (one shared from another project) has no action. */
export const ARowWithNoActionsShowsNoButton: Story = {
  args: { actionsOf: () => null, linkTo: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("link")).not.toBeInTheDocument();
    await expect(within(canvasElement).getByText("CON-001")).toBeInTheDocument();
  },
};

/** An element page lists the connection's own name after the code. */
export const ShowNameAddsTheConnectionName: Story = {
  args: { showName: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Admin traffic")).toBeInTheDocument();
    await userEvent.tab();
    await expect(within(canvasElement).getAllByRole("link")[0]).toHaveFocus();
  },
};

/** With `onChoose` the two lines are one button (the code is text, not a link), chosen by click or Enter, and fit the narrow card. */
export const AChoosableRowIsOneButtonThatFitsTheCard: Story = {
  args: { onChoose: fn(), linkTo: undefined, connections: [buildConnection({ unique_code: "F3ID-CON-003" })] },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
    const choose = canvas.getByRole("button", { name: /^F3ID-CON-003 REST API/ });
    await expect(choose).toHaveAccessibleName(/Gateway to Orders$/);
    await userEvent.click(choose);
    await expect(args.onChoose).toHaveBeenCalledTimes(1);
    choose.focus();
    await userEvent.keyboard("{Enter}");
    await expect(args.onChoose).toHaveBeenCalledTimes(2);
    const list = canvasElement.querySelector<HTMLElement>(".item-row-list")!;
    await expect(list.scrollWidth).toBeLessThanOrEqual(list.clientWidth + 1);
    await expect(orphanedControlViolations(canvasElement)).toEqual([]);
  },
};

/** The row named by `focusId` takes the keyboard focus when it appears (the way back from a chosen connection). */
export const TheRowNamedByFocusIdTakesTheFocus: Story = {
  args: { onChoose: fn(), focusId: "con-2", linkTo: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: /^CON-002 / })).toHaveFocus();
  },
};
