import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { FilterCheckbox, FilterField, FilterPanel } from "./FilterPanel";

/** Wraps all three exports together, matching how RequirementsPage/
 * ChangeRequestsPage actually compose them: a panel shell containing
 * labelled fields, one of which is a checkbox. */
function Interactive() {
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  return (
    <FilterPanel>
      <FilterField label="Search">
        <input className="input" value={search} onChange={(e) => setSearch(e.target.value)} />
      </FilterField>
      <FilterField label="Status">
        <FilterCheckbox label="Include archived" checked={archived} onChange={setArchived} />
      </FilterField>
    </FilterPanel>
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/FilterPanel",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Search")).toBeInTheDocument();
    const checkbox = canvas.getByLabelText("Include archived");
    await expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    await expect(checkbox).toBeChecked();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
