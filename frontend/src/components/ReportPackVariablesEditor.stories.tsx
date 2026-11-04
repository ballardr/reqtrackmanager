import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import { ReportPackVariablesEditor, type DraftVariable } from "./ReportPackVariablesEditor";

/** The Variables tab of the pack editor: the choices a person makes once when downloading the pack. */
const meta: Meta<typeof ReportPackVariablesEditor> = {
  title: "Components/Reports/ReportPackVariablesEditor",
  component: ReportPackVariablesEditor,
};
export default meta;

type Story = StoryObj<typeof ReportPackVariablesEditor>;

const catalogue = buildFieldCatalogue();

function Harness({ start, disabled = false, withCatalogue = true }: { start: DraftVariable[]; disabled?: boolean; withCatalogue?: boolean }) {
  const [variables, setVariables] = useState(start);
  return (
    <>
      <ReportPackVariablesEditor variables={variables} onChange={setVariables} catalogue={withCatalogue ? catalogue : null} disabled={disabled} />
      <pre data-testid="json">{JSON.stringify(variables.map((v) => v.variable))}</pre>
    </>
  );
}

const status: DraftVariable = {
  uid: "v1", variable: { name: "status", type: "enum", label: "Status", multiple: true, source: { record_type: "requirement", field: "status" } },
};

export const ShowsEachDeclaration: Story = {
  render: () => <Harness start={[status]} />,
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole("region", { name: "Variable 1" }));
    await expect(card.getByRole("textbox", { name: /^Name/ })).toHaveValue("status");
    await expect(card.getByRole("combobox", { name: /^Type/ })).toHaveValue("enum");
    await expect(card.getByRole("combobox", { name: /^Take options from/ })).toHaveValue("requirement");
    await expect(card.getByRole("combobox", { name: "Field" })).toHaveValue("status");
  },
};

export const AddingAVariableStartsAsText: Story = {
  render: () => <Harness start={[]} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByText("This pack has no variables.")).toBeInTheDocument();
    await userEvent.click(view.getByRole("button", { name: "Add a variable" }));
    await userEvent.type(view.getByRole("textbox", { name: /^Name/ }), "team");
    await expect(view.getByTestId("json")).toHaveTextContent('[{"name":"team","type":"text"}]');
  },
};

export const ATrailingCommaSurvivesWhileTypingAList: Story = {
  render: () => <Harness start={[{ uid: "v2", variable: { name: "level", type: "enum" } }]} withCatalogue={false} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const options = await view.findByRole("textbox", { name: "Options" });
    await userEvent.type(options, "Low, High,");
    await expect(options).toHaveValue("Low, High,");
    await expect(view.getByTestId("json")).toHaveTextContent('"options":["Low","High"]');
  },
};

export const ChangingTheTypeDropsWhatNoLongerApplies: Story = {
  render: () => <Harness start={[{ uid: "v3", variable: { name: "level", type: "enum", options: ["A", "B"] } }]} withCatalogue={false} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.selectOptions(await view.findByRole("combobox", { name: /^Type/ }), "text");
    await expect(view.getByTestId("json")).toHaveTextContent('[{"name":"level","type":"text"}]');
  },
};

export const ASharedPackIsReadOnly: Story = {
  render: () => <Harness start={[status]} disabled />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByRole("textbox", { name: /^Name/ })).toBeDisabled();
    await expect(view.queryByRole("button", { name: "Add a variable" })).not.toBeInTheDocument();
  },
};
