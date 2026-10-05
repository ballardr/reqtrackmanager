import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { GuidingPrincipleRelationshipsSection } from "./GuidingPrincipleRelationshipsSection";
import type { ContextStrategyLink, GuidingPrinciple } from "./types";

const PROJECT_ID = "project-1";

function guidingPrinciple(overrides: Partial<GuidingPrinciple> = {}): GuidingPrinciple {
  return {
    id: "gp-1", scope: "project", organization_id: null, project_id: PROJECT_ID, creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, name: "Field data is captured once",
    principle_statement: "Every field observation is recorded exactly once, at the point of inspection.",
    rationale: "", priority: "high", status: "active", owner_id: null, version_number: 3, is_locked: true,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

function link(overrides: Partial<ContextStrategyLink> = {}): ContextStrategyLink {
  return {
    id: "link-1", source_type: "guiding_principle", source_id: "gp-1", target_type: "strategy",
    target_id: "strategy-1", link_type_id: "linktype-1", direction: "outgoing", display_name: "Supports",
    other_type: "strategy", other_id: "strategy-1", other_display_code: null,
    other_display_name: "Lead the regional market", created_by: "user-1",
    created_at: "2026-02-02T09:00:00Z", ...overrides,
  };
}

const meta: Meta<typeof GuidingPrincipleRelationshipsSection> = {
  title: "Modules/ContextStrategy/GuidingPrincipleRelationshipsSection",
  component: GuidingPrincipleRelationshipsSection,
  args: { guidingPrinciple: guidingPrinciple(), projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof GuidingPrincipleRelationshipsSection>;

export const NoRelationshipsYet: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No relationships yet.")).toBeInTheDocument());
    await expect(canvas.getByText(/guides → Decision/)).toBeInTheDocument();
  },
};

export const ListsExistingRelationships: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) {
        return [
          link(),
          link({ id: "link-2", target_type: "requirement", other_type: "requirement", display_name: "Informs", other_display_code: "MKT-001", other_display_name: "Expand into two new territories" }),
        ];
      }
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Supports")).toBeInTheDocument());
    await expect(canvas.getByText(/Lead the regional market/)).toBeInTheDocument();
    await expect(canvas.getByText("Informs")).toBeInTheDocument();
    await expect(canvas.getByText(/MKT-001/)).toBeInTheDocument();
  },
};

export const AddSupportsStrategyLink: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/strategies")) {
        return [{ id: "strategy-1", title: "Lead the regional market" }];
      }
      return [];
    });
    spyOn(api, "post").mockImplementation(async () => link());
  },
  args: { onChanged: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Strategy"));
    await userEvent.selectOptions(canvas.getByLabelText("Strategy"), "strategy-1");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/gp-1/relationships`,
      { kind: "supports_strategy", target_id: "strategy-1" }
    ));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

export const AddInformsRequirementLink: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/requirements")) {
        return [{ id: "requirement-1", unique_code: "MKT-001", name: "Expand into two new territories" }];
      }
      return [];
    });
    spyOn(api, "post").mockImplementation(async () => link({ display_name: "Informs" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Relationship"));
    await userEvent.selectOptions(canvas.getByLabelText("Relationship"), "informs_requirement");
    await waitFor(() => canvas.getByLabelText("Requirement"));
    await userEvent.selectOptions(canvas.getByLabelText("Requirement"), "requirement-1");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/guiding-principles/gp-1/relationships`,
      { kind: "informs_requirement", target_id: "requirement-1" }
    ));
  },
};

/** An org-scoped Guiding Principle has no single project to search a
 * Requirement within — only "Supports a Strategy" and "Supersedes another
 * Guiding Principle" are offered (see this component's own module docstring
 * for the reasoning, mirroring `StrategyRelationshipsSection.stories.tsx`'s
 * own `OrgScopedOffersFewerKinds` case). */
export const OrgScopedOffersFewerKinds: Story = {
  args: { guidingPrinciple: guidingPrinciple({ scope: "organization", organization_id: "org-1", project_id: null }), projectId: undefined, organizationId: "org-1" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/relationships")) return [];
      if (path.includes("/orgs/org-1/modules/context_strategy/strategies")) return [{ id: "strategy-1", title: "Lead the regional market" }];
      return [];
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Relationship"));
    await expect(canvas.queryByText("Informs a Requirement")).not.toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Supports a Strategy" })).toBeInTheDocument();
    await expect(canvas.getByRole("option", { name: "Supersedes another Guiding Principle" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsExistingRelationships };
export const DarkTheme: Story = { ...ListsExistingRelationships, globals: { theme: "dark" } };
