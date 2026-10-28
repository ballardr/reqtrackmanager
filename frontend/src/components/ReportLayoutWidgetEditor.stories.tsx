import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildWidgets } from "../testing/reportLayoutFixtures";
import { WidgetKeyField, WidgetParamsField, WidgetSortField } from "./ReportLayoutWidgetEditor";

const widgets = buildWidgets();

function Harness({ initial }: { initial: Record<string, unknown> }) {
  const [node, setNode] = useState(initial);
  const key = typeof node.key === "string" ? node.key : "";
  return (
    <>
      <WidgetKeyField widgets={widgets} value={key} onChange={(next) => setNode({ ...node, key: next })} />
      <WidgetParamsField
        widget={widgets.find((w) => w.key === key)} value={(node.params ?? {}) as Record<string, unknown>}
        onChange={(params) => setNode({ ...node, params })}
      />
      <WidgetSortField value={(node.sort ?? []) as { column?: string }[]} onChange={(sort) => setNode({ ...node, sort })} />
      <pre data-testid="value" hidden>{JSON.stringify(node)}</pre>
    </>
  );
}

/** The three controls of a widget block: the component, its report's own settings and a sort of its table. */
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutWidgetEditor", component: Harness, args: { initial: { key: "" } } };
export default meta;

type Story = StoryObj<typeof Harness>;

const valueOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("value").textContent ?? "null");

export const ComponentsAreLabelledWithTheirModule: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: /Component/ }) as HTMLSelectElement;
    await expect(Array.from(select.options).map((o) => o.text)).toEqual([
      "Choose a component…", "Risk Management: Risk register", "Risk Management: Headline figures",
      "Decision Management: Decision register", "Decision Management: Approval ageing", "Decision Management: Decision log",
    ]);
    await expect(canvas.getByText("This component has no settings.")).toBeInTheDocument();
    await userEvent.selectOptions(select, "risk_management.risk-register.register");
    await waitFor(() => expect(valueOf(canvasElement).key).toBe("risk_management.risk-register.register"));
    // The report's own settings now appear, drawn by the shared parameter form.
    await expect(await canvas.findByLabelText("Lowest rating")).toBeInTheDocument();
  },
};

export const SettingsAreSetAndEmptiedAway: Story = {
  args: { initial: { key: "risk_management.risk-register.register" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rating = await canvas.findByLabelText("Lowest rating");
    await userEvent.type(rating, "5");
    await waitFor(() => expect(valueOf(canvasElement).params).toEqual({ min_rating: 5 }));
    await userEvent.clear(rating);
    // The last setting removed takes the whole `params` key with it.
    await waitFor(() => expect(valueOf(canvasElement)).not.toHaveProperty("params"));
  },
};

export const ASettingBoundToAVariableIsKeptNotDrawn: Story = {
  args: { initial: { key: "risk_management.risk-register.register", params: { min_rating: { var: "floor" } } } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Uses variable floor")).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Lowest rating")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Use a value" }));
    await waitFor(() => expect(valueOf(canvasElement)).not.toHaveProperty("params"));
    await expect(await canvas.findByLabelText("Lowest rating")).toBeInTheDocument();
  },
};

export const AKeyTheScopeNoLongerOffersStaysVisible: Story = {
  args: { initial: { key: "gone.report.part" } },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: /Component/ }) as HTMLSelectElement;
    await expect(select.value).toBe("gone.report.part");
    await expect(select.options[1].text).toBe("gone.report.part (not available here)");
  },
};

export const SortKeysAreAddedUpToThreeAndRemoved: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (let i = 0; i < 3; i += 1) await userEvent.click(canvas.getByRole("button", { name: "Add sort" }));
    await expect(canvas.queryByRole("button", { name: "Add sort" })).not.toBeInTheDocument();
    await userEvent.type(canvas.getByRole("textbox", { name: "Sort column 1" }), "Rating");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Sort column 1: Descending" }));
    await waitFor(() => expect(valueOf(canvasElement).sort[0]).toEqual({ column: "Rating", descending: true }));
    for (const n of [3, 2, 1]) await userEvent.click(canvas.getByRole("button", { name: `Remove sort key ${n}` }));
    await waitFor(() => expect(valueOf(canvasElement)).not.toHaveProperty("sort"));
  },
};
