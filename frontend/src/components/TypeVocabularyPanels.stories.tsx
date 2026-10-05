import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { withToast } from "../testing/storybook-helpers";
import {
  type EffectiveTypeRow,
  type OrgTypeRow,
  OrgTypeVocabularyPanel,
  ProjectTypeVocabularyPanel,
} from "./TypeVocabularyPanels";

/** A stateful in-memory org-tier API: `create`/`update`/`move` mutate `items`,
 * and a type named "In use" refuses deletion with a 409 like the real backend. */
function orgApi(initial: OrgTypeRow[]) {
  let items = initial;
  return {
    async list() {
      return items;
    },
    async create(_orgId: string, name: string) {
      items = [...items, { id: `type-${items.length + 1}`, name, is_active: true }];
    },
    async move(_orgId: string, id: string, direction: "up" | "down") {
      const idx = items.findIndex((i) => i.id === id);
      const swap = direction === "up" ? idx - 1 : idx + 1;
      if (swap < 0 || swap >= items.length) return;
      const next = [...items];
      [next[idx], next[swap]] = [next[swap], next[idx]];
      items = next;
    },
    async update(_orgId: string, id: string, values: { name?: string; is_active?: boolean }) {
      items = items.map((i) => (i.id === id ? { ...i, ...values } : i));
    },
    async delete(_orgId: string, id: string) {
      if (items.find((i) => i.id === id)?.name === "In use") throw new ApiError(409, "Referenced.");
      items = items.filter((i) => i.id !== id);
    },
  };
}

function projectApi(initial: EffectiveTypeRow[]) {
  let items = initial;
  return {
    async list() {
      return items;
    },
    async createLocal(_projectId: string, name: string, displayOrder?: number) {
      items = [...items, { id: `local-${items.length + 1}`, name, display_order: displayOrder ?? 0, is_enabled: true, source: "project_local" as const }];
    },
    async override(_projectId: string, id: string, values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null }) {
      items = items.map((i) =>
        i.id === id
          ? {
              ...i,
              name: values.name ?? i.name,
              display_order: values.display_order ?? i.display_order,
              is_enabled: values.is_enabled ?? i.is_enabled,
              source: i.source === "org" ? ("project_override" as const) : i.source,
            }
          : i,
      );
    },
    async delete(_projectId: string, id: string) {
      if (items.find((i) => i.id === id)?.name === "In use") throw new ApiError(409, "Referenced.");
      items = items.filter((i) => i.id !== id);
    },
  };
}

const meta: Meta = {
  title: "Components/TypeVocabularyPanels",
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj;

export const OrgTierLabelsComeFromTheNoun: Story = {
  render: () => (
    <OrgTypeVocabularyPanel
      orgId="org-1"
      noun="Widget"
      description="Org-level Widget types."
      api={orgApi([{ id: "t1", name: "Alpha", is_active: true }])}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Alpha")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Widget type name")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Add Widget type" })).toBeInTheDocument();
  },
};

export const OrgTierAddAndToggle: Story = {
  render: () => (
    <OrgTypeVocabularyPanel orgId="org-1" noun="Widget" description="d" api={orgApi([{ id: "t1", name: "Alpha", is_active: true }])} />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByPlaceholderText("Widget type name"));
    await userEvent.type(canvas.getByPlaceholderText("Widget type name"), "Beta");
    await userEvent.click(canvas.getByRole("button", { name: "Add Widget type" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Beta")).toBeInTheDocument());

    const toggle = await canvas.findByRole("switch", { name: "Active: Alpha" });
    await userEvent.click(toggle);
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Active: Alpha" })).toHaveAttribute("aria-checked", "false"));
  },
};

export const OrgTierDeleteInUseShowsPlainError: Story = {
  render: () => (
    <OrgTypeVocabularyPanel
      orgId="org-1" noun="Widget" description="d" inUseMessage="Still used somewhere."
      api={orgApi([{ id: "t1", name: "In use", is_active: true }, { id: "t2", name: "Spare", is_active: true }])}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("In use"));
    const row = canvas.getByDisplayValue("In use").closest("div")!.parentElement!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete Widget type" }));
    await waitFor(() => expect(canvas.getByText("Still used somewhere.")).toBeInTheDocument());
    await expect(canvas.queryByText(/Reassign/)).not.toBeInTheDocument();
  },
};

export const OrgTierLoadErrorShowsInlineMessage: Story = {
  render: () => (
    <OrgTypeVocabularyPanel
      orgId="org-1" noun="Widget" description="d"
      api={{ ...orgApi([]), list: async () => { throw new ApiError(404, "Module is not enabled."); } }}
    />
  ),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Module is not enabled.")).toBeInTheDocument());
  },
};

export const ProjectTierShowsSourcesAndOverrides: Story = {
  render: () => (
    <ProjectTypeVocabularyPanel
      projectId="project-1" noun="Widget" description="d"
      api={projectApi([
        { id: "a", name: "Alpha", display_order: 0, is_enabled: true, source: "org" },
        { id: "b", name: "Beta", display_order: 1, is_enabled: true, source: "project_override" },
        { id: "c", name: "Gamma", display_order: 2, is_enabled: true, source: "project_local" },
      ])}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Alpha")).toBeInTheDocument());
    await expect(canvas.getByText("Org default")).toBeInTheDocument();
    await expect(canvas.getByText("Org default (overridden)")).toBeInTheDocument();
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};

export const ProjectTierRenameAndDisable: Story = {
  render: () => (
    <ProjectTypeVocabularyPanel
      projectId="project-1" noun="Widget" description="d"
      api={projectApi([{ id: "a", name: "Alpha", display_order: 0, is_enabled: true, source: "org" }])}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await canvas.findByDisplayValue("Alpha");
    await userEvent.clear(input);
    await userEvent.type(input, "Renamed");
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(canvas.getByText("Org default (overridden)")).toBeInTheDocument());

    const toggle = canvas.getByRole("switch", { name: "Enabled: Renamed" });
    await userEvent.click(toggle);
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Enabled: Renamed" })).toHaveAttribute("aria-checked", "false"));
  },
};

export const ProjectTierRefusesToDeleteUntouchedOrgDefault: Story = {
  render: () => (
    <ProjectTypeVocabularyPanel
      projectId="project-1" noun="Widget" description="d"
      api={projectApi([
        { id: "a", name: "Alpha", display_order: 0, is_enabled: true, source: "org" },
        { id: "c", name: "Gamma", display_order: 1, is_enabled: true, source: "project_local" },
      ])}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("Alpha"));
    const row = canvas.getByDisplayValue("Alpha").closest("div")!.parentElement!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete Widget type" }));
    await waitFor(() => expect(canvas.getByText(/nothing to delete. Disable it instead/)).toBeInTheDocument());
  },
};

export const ProjectTierDeleteInUseShowsPlainError: Story = {
  render: () => (
    <ProjectTypeVocabularyPanel
      projectId="project-1" noun="Widget" description="d"
      api={projectApi([
        { id: "c", name: "In use", display_order: 0, is_enabled: true, source: "project_local" },
        { id: "d", name: "Spare", display_order: 1, is_enabled: true, source: "project_local" },
      ])}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByDisplayValue("In use"));
    const row = canvas.getByDisplayValue("In use").closest("div")!.parentElement!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete Widget type" }));
    await waitFor(() =>
      expect(canvas.getByText("This type is still used by at least one Widget in this project. Disable it instead of deleting it.")).toBeInTheDocument(),
    );
  },
};

export const DarkTheme: Story = { ...ProjectTierShowsSourcesAndOverrides, globals: { theme: "dark" } };
