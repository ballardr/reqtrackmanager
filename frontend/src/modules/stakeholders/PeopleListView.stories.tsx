import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, screen, userEvent, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../../testing/storybook-helpers";
import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { PeopleListView } from "./PeopleListView";
import type { PeopleRow } from "./peopleRows";
import type { Persona } from "./types";

function row(n: number, long: boolean): PeopleRow {
  const kind = (["persona", "stakeholder", "group"] as const)[n % 3];
  return {
    id: `p${n}`, unique_code: stressText(long, `PER-00${n}`, "code"), name: stressText(long, ["Launch-site customers", "Compliance Auditor", "Operations"][n % 3]),
    kind, summary: stressText(long, "Reviews every release", "summary"), typeName: stressText(long, "Customer", "word"),
    status: "active", scope: n === 1 ? "organization" : "project", source: {} as Persona,
  };
}

const rows = (long: boolean) => [0, 1, 2].map((n) => row(n, long));

/** The combined People list: Name, Code and Status always drawn, Kind, Details and Type optional, Scope off until chosen. */
const meta: Meta<typeof PeopleListView> = {
  title: "Modules/Stakeholders/PeopleListView",
  component: PeopleListView,
  decorators: [withStatefulAuth(buildUser()), (Story) => <MemoryRouter><Story /></MemoryRouter>],
  args: { rows: rows(false), includeArchived: false, onIncludeArchivedChange: fn(), includeHidden: false, onOpen: fn() },
};
export default meta;

type Story = StoryObj<typeof PeopleListView>;

/** Scope is not a default column; the chooser adds it. */
export const ScopeIsChosenNotDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const header of ["Name", "Code", "Kind", "Details", "Type", "Status"]) await expect(canvas.getByRole("columnheader", { name: header })).toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Scope" }));
    await expect(canvas.getByRole("columnheader", { name: "Scope" })).toBeInTheDocument();
  },
};

/** Long names, details and codes at the page's usual width: the Name column keeps its floor and the table keeps its shape. */
export const LongText: Story = {
  render: (args) => <TextStress width={960} render={(long) => <PeopleListView {...args} rows={rows(long)} />} />,
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};
