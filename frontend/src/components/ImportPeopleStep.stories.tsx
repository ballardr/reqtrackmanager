import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import type { ImportPeopleChoices } from "../api/types";
import { ImportPeopleStep } from "./ImportPeopleStep";

const PEOPLE = [
  { email: "alex@old.example", display_name: "Alex Morgan", resolution: "stand_in" as const, member_id: null, member_name: null },
  { email: "sam@new.example", display_name: "Sam Lee", resolution: "member" as const, member_id: "u-sam", member_name: "Sam Lee" },
  { email: "kim@old.example", display_name: "Kim Ito", resolution: "reassigned" as const, member_id: "u-sam", member_name: "Sam Lee" },
];

const meta: Meta<typeof ImportPeopleStep> = {
  title: "Components/ImportPeopleStep",
  component: ImportPeopleStep,
  args: { people: PEOPLE, members: [{ user_id: "u-sam", display_name: "Sam Lee" }, { user_id: "u-pat", display_name: "Pat Doe" }], choices: { mapping: {}, keep_original_email: false }, onChange: () => {} },
};
export default meta;

type Story = StoryObj<typeof ImportPeopleStep>;

/** Each person with how they will be recorded; an imported person is badged as such. */
export const Preview: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "People in the bundle" }));
    await expect(table.getAllByText("Imported person").length).toBeGreaterThan(0);
    await expect(table.getByText("Member: Sam Lee")).toBeInTheDocument();
    await expect(table.getByText("Reassigned: Sam Lee")).toBeInTheDocument();
    await expect(table.getByRole("button", { name: "Help: Change" })).toBeInTheDocument();
  },
};

function Controlled(args: React.ComponentProps<typeof ImportPeopleStep>) {
  const [choices, setChoices] = useState<ImportPeopleChoices>(args.choices);
  return <ImportPeopleStep {...args} choices={choices} onChange={setChoices} />;
}

/** Choosing a member for a person, and the keep-email switch, update the choices. */
export const Choosing: Story = {
  render: (args) => <Controlled {...args} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Import Alex Morgan as" });
    await userEvent.selectOptions(select, "u-pat");
    await expect(select).toHaveValue("u-pat");
    await userEvent.selectOptions(select, "");
    await expect(select).toHaveValue("");
    const keep = canvas.getByRole("checkbox", { name: "Keep original email addresses in the history" });
    await userEvent.click(keep);
    await expect(keep).toBeChecked();
  },
};

export const Loading: Story = {
  args: { loading: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent("Reading the people in the bundle…");
  },
};

export const NoPeople: Story = {
  args: { people: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("The bundle names no people.")).toBeInTheDocument();
  },
};
