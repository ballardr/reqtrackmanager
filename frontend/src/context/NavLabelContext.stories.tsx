import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { NavLabels } from "../api/types";
import { ListPageLayout } from "../components/ListPageLayout";
import { RecordHeader } from "../components/RecordHeader";
import { NavLabelProvider } from "./NavLabelContext";

const LIST = "/projects/project-1/modules/decisions";

const NAMES: NavLabels = {
  items: [
    { key: "decisions:", label: "Decisions", path: LIST, effective: "ADRs", own: "ADRs" },
    { key: "requirements", label: "Requirements", path: "/projects/project-1/requirements", effective: null },
  ],
};

/** The page title and a record's back link follow the name given to the navigation entry. */
const meta: Meta = {
  title: "Context/NavLabelContext",
  parameters: { layout: "fullscreen" },
};
export default meta;

type Story = StoryObj;

function Page({ path, back }: { path: string; back: string }) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <NavLabelProvider projectId="project-1">
        <ListPageLayout title="Decisions" filter={<div />}>
          <RecordHeader recordLabel="Decision" title="Adopt PostgreSQL" back={{ to: back, label: "Decisions" }} />
        </ListPageLayout>
      </NavLabelProvider>
    </MemoryRouter>
  );
}

/** A renamed entry replaces the built-in title and back-link label. */
export const RenamedEntryReplacesTitleAndBackLink: Story = {
  render: () => <Page path={LIST} back={`${LIST}?status=open`} />,
  beforeEach: () => { spyOn(api, "get").mockResolvedValue(NAMES); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { level: 1, name: "ADRs" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "← ADRs" })).toBeInTheDocument();
  },
};

/** An entry with no name keeps its built-in title and back-link label, as does a page that is not an entry. */
export const UnnamedEntryKeepsBuiltInNames: Story = {
  render: () => <Page path="/projects/project-1/requirements" back="/projects/project-1/requirements" />,
  beforeEach: () => { spyOn(api, "get").mockResolvedValue(NAMES); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { level: 1, name: "Decisions" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "← Decisions" })).toBeInTheDocument();
  },
};
