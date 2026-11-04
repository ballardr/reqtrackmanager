import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportSnippetFields } from "./ReportSnippetFields";

/** The fields with their own state, as a form would hold it. */
function Harness() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  return (
    <div className="stack">
      <ReportSnippetFields
        name={name} description={description} category={category} categories={["House style", "Notes"]}
        onName={setName} onDescription={setDescription} onCategory={setCategory}
      />
    </div>
  );
}

/** The name, description and category a saved snippet's save and edit forms share. Only the name is required. */
const meta: Meta<typeof ReportSnippetFields> = {
  title: "Components/Reports/ReportSnippetFields",
  component: ReportSnippetFields,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  render: () => <Harness />,
};
export default meta;

type Story = StoryObj<typeof ReportSnippetFields>;

export const MarksOnlyTheNameRequiredAndSuggestsTheCategories: Story = {
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Name"]);
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox", { name: "Category" }), "Notes");
    await expect(canvas.getByRole("combobox", { name: "Category" })).toHaveValue("Notes");
    await expect([...canvasElement.querySelectorAll("datalist option")].map((o) => (o as HTMLOptionElement).value)).toEqual(["House style", "Notes"]);
    await expect(canvas.getByRole("button", { name: "Help: Category" })).toBeInTheDocument();
  },
};
