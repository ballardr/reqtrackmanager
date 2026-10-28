import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { PackVariableDeclaration } from "../api/reportPacks";
import { buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import { ReportLayoutVariablesField } from "./ReportLayoutVariablesField";

function Harness({ initial }: { initial?: PackVariableDeclaration[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportLayoutVariablesField value={value} onChange={setValue} catalogue={buildFieldCatalogue()} />
      <pre data-testid="value" hidden>{JSON.stringify(value) ?? "undefined"}</pre>
    </>
  );
}

/** A layout's run-time variables, declared with the editor a report pack uses, worded for a layout. */
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutVariablesField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const valueOf = (el: HTMLElement) => within(el).getByTestId("value").textContent;

export const NoVariablesIsWordedForALayout: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("This layout has no variables.")).toBeInTheDocument();
    await expect(canvas.queryByText(/pack/i)).not.toBeInTheDocument();
  },
};

export const AddingAndRemovingAVariableKeepsTheListOrDropsTheKey: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add a variable" }));
    await waitFor(() => expect(JSON.parse(valueOf(canvasElement) ?? "null")).toHaveLength(1));
    await userEvent.click(canvas.getByRole("button", { name: /Remove variable/ }));
    await waitFor(() => expect(valueOf(canvasElement)).toBe("undefined"));
  },
};

export const DeclaredVariablesAreShownWithTheirNames: Story = {
  args: { initial: [{ name: "wanted", type: "text", label: "Wanted" }] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByDisplayValue("wanted")).toBeInTheDocument();
  },
};
