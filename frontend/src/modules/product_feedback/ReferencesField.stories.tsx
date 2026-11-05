import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { ReferenceDraft } from "./referenceDraft";
import { referencesPayload } from "./referenceDraft";
import { ReferencesField } from "./ReferencesField";
import { SYSTEM_CHOICES } from "./requestFixtures";

function Harness({ initial = [] as ReferenceDraft[] }) {
  const [value, setValue] = useState<ReferenceDraft[]>(initial);
  return (
    <div className="stack">
      <ReferencesField value={value} onChange={setValue} systems={SYSTEM_CHOICES} />
      <output aria-label="Payload">{JSON.stringify(referencesPayload(value))}</output>
    </div>
  );
}

const meta: Meta<typeof Harness> = { title: "Modules/ProductFeedback/ReferencesField", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

/** Rows are added and removed in place; a row with no system, or neither key nor link, is left out of what is sent. */
export const AddsRowsAndSendsOnlyTheCompleteOnes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Add a reference/ }));
    await userEvent.click(canvas.getByRole("button", { name: /Add a reference/ }));
    await expect(canvas.getByLabelText("Reference 2 system")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Payload")).toHaveTextContent("[]");

    await userEvent.selectOptions(canvas.getByLabelText("Reference 1 system"), "system-jira");
    await userEvent.type(canvas.getByLabelText("Reference 1 key"), "PROJ-1");
    await userEvent.selectOptions(canvas.getByLabelText("Reference 1 role"), "origin");
    await expect(canvas.getByLabelText("Payload")).toHaveTextContent(
      JSON.stringify([{ system_id: "system-jira", key: "PROJ-1", url: null, role: "origin" }]),
    );
    await userEvent.click(canvas.getByRole("button", { name: "Remove reference 2" }));
    await expect(canvas.queryByLabelText("Reference 2 system")).not.toBeInTheDocument();
  },
};

/** A link alone is enough, and the system is the only required mark. */
export const ALinkAloneIsEnough: Story = {
  args: { initial: [{ systemId: "system-servicenow", key: "", url: "https://sn.example.com/INC1", role: "delivery" }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Payload")).toHaveTextContent(
      JSON.stringify([{ system_id: "system-servicenow", key: "", url: "https://sn.example.com/INC1", role: "delivery" }]),
    );
  },
};
