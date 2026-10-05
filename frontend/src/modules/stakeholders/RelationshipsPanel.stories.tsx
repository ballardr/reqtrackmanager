import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { withToast } from "../../testing/storybook-helpers";
import { buildRelationship, buildRelationshipKinds } from "./fixtures";
import { RelationshipsPanel, type RelationshipPanelApi } from "./RelationshipsPanel";
import type { RelationshipTarget } from "./types";

const TARGETS: Record<string, RelationshipTarget[]> = {
  pain_point: [
    { id: "pp-1", label: "Reports arrive late" },
    { id: "pp-2", label: "Manual re-keying" },
  ],
  requirement: [{ id: "req-1", label: "REQ-001 Remote diagnostics in 30 seconds" }],
  decision: [{ id: "dec-1", label: "DEC-001 Use Postgres" }],
};

function buildApi(overrides: Partial<RelationshipPanelApi> = {}): RelationshipPanelApi {
  return {
    kinds: fn(async () => buildRelationshipKinds()),
    targets: fn(async (_projectId: string, type: string) => TARGETS[type] ?? []),
    list: fn(async () => [
      buildRelationship(),
      buildRelationship({
        link_id: "rel-2", kind: "provides_requirement", forward: "Provides", target_type: "requirement",
        target_id: "req-1", label: "REQ-001 Remote diagnostics in 30 seconds",
      }),
    ]),
    add: fn(async () => buildRelationship()),
    remove: fn(async () => undefined),
    ...overrides,
  };
}

const meta: Meta<typeof RelationshipsPanel> = {
  title: "Modules/Stakeholders/RelationshipsPanel",
  component: RelationshipsPanel,
  decorators: [
    withToast(),
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: { projectId: "project-1", holder: "stakeholder", holderId: "stakeholder-1", api: buildApi() },
};
export default meta;

type Story = StoryObj<typeof RelationshipsPanel>;

export const GroupsLinksByKindAndLinksToEachRecord: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Experiences", { selector: "span" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Reports arrive late" })).toHaveAttribute(
      "href", "/projects/project-1/modules/context_strategy/pain-points/pp-1",
    );
    // A Requirement resolves through core's route; its kind is a label, never the raw key.
    await expect(canvas.getByRole("link", { name: /REQ-001/ })).toHaveAttribute("href", "/projects/project-1/requirements/req-1");
    await expect(canvas.getByText("Pain Point:")).toBeInTheDocument();
    await expect(canvas.queryByText("experiences_pain_point")).not.toBeInTheDocument();
  },
};

export const ReservedKindIsANoteNotAnOption: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Relationship" }));
    await expect(canvas.getByText(/Uses Design \/ System Element: available once the module that provides it is installed\./)).toBeInTheDocument();
    await expect(canvas.queryByRole("option", { name: "Uses" })).not.toBeInTheDocument();
  },
};

export const PersonaOnlyGetsTheKindsThatApplyToIt: Story = {
  args: { holder: "persona" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Relationship" }));
    for (const name of ["Experiences", "Provides", "Is affected by"]) {
      await expect(canvas.getByRole("option", { name })).toBeInTheDocument();
    }
    for (const name of ["Consulted on", "Approves", "Reviews"]) {
      await expect(canvas.queryByRole("option", { name })).not.toBeInTheDocument();
    }
  },
};

export const EmptyState: Story = {
  args: { api: buildApi({ list: fn(async () => []) }) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No relationships to this project's records yet.")).toBeInTheDocument());
  },
};

export const RendersNothingWithoutAProject: Story = {
  args: { projectId: undefined },
  play: async ({ canvasElement, args }) => {
    await new Promise((resolve) => setTimeout(resolve, 50));
    await expect(args.api?.kinds).not.toHaveBeenCalled();
    await expect(within(canvasElement).queryByText("Relationships")).not.toBeInTheDocument();
  },
};

/** The panel renders nothing when the list can't be loaded (e.g. the holder's sub-component is switched off). */
export const HidesItselfWhenTheLoadFails: Story = {
  args: { api: buildApi({ list: fn(async () => { throw new Error("404"); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api?.list).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Relationships")).not.toBeInTheDocument();
  },
};

export const AddOffersOnlyUnlinkedTargets: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Relationship" }));
    await expect(canvas.getByRole("button", { name: "Add relationship" })).toBeDisabled();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Relationship" }), "experiences_pain_point");
    await waitFor(() => canvas.getByRole("combobox", { name: "Pain Point" }));
    // The already-linked Pain Point is not offered again.
    await expect(canvas.queryByRole("option", { name: "Reports arrive late" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Pain Point" }), "pp-2");
    await userEvent.click(canvas.getByRole("button", { name: "Add relationship" }));
    await waitFor(() =>
      expect(args.api?.add).toHaveBeenCalledWith("project-1", "stakeholder", "stakeholder-1", "experiences_pain_point", "pain_point", "pp-2"),
    );
  },
};

export const KindWithTwoTargetTypesAsksForTheType: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Relationship" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Relationship" }), "approves");
    await expect(canvas.queryByRole("combobox", { name: "Decision" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Target type" }), "decision");
    await waitFor(() => canvas.getByRole("combobox", { name: "Decision" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Decision" }), "dec-1");
    await userEvent.click(canvas.getByRole("button", { name: "Add relationship" }));
    await waitFor(() =>
      expect(args.api?.add).toHaveBeenCalledWith("project-1", "stakeholder", "stakeholder-1", "approves", "decision", "dec-1"),
    );
  },
};

export const RemoveAsksForConfirmation: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove Experiences Reports arrive late" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove Experiences Reports arrive late" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Remove this relationship?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(args.api?.remove).toHaveBeenCalledWith("project-1", "stakeholder", "stakeholder-1", "rel-1"));
  },
};

export const DarkTheme: Story = { ...GroupsLinksByKindAndLinksToEachRecord, globals: { theme: "dark" } };
