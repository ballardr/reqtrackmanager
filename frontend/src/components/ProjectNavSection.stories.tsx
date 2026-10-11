import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { buildProjectNavItems, NAV_PROJECT_ID } from "../testing/projectNavFixtures";
import { ProjectNavSection } from "./ProjectNavSection";

/**
 * The nav rail's "Project" section with the user's layout applied (docs/plans/platform-
 * enhancements-2026-10-plan.md Phase 4). Rendered in a plain 240px column rather than inside the
 * fixed-position `.nav-rail`, which is `Layout`'s concern.
 */
const meta: Meta<typeof ProjectNavSection> = {
  title: "Components/ProjectNavSection",
  component: ProjectNavSection,
  args: { projectId: NAV_PROJECT_ID, items: buildProjectNavItems(), railCollapsed: false },
  decorators: [
    (Story) => (
      <div className="stack" style={{ width: 240, gap: "0.15rem" }}>
        <Story />
      </div>
    ),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectNavSection>;

const links = (canvas: { getAllByRole: (role: string) => HTMLElement[] }) =>
  canvas.getAllByRole("link").map((link) => link.getAttribute("aria-label"));

export const ProductDefaultOrder: Story = {
  decorators: [withRouter(`/projects/${NAV_PROJECT_ID}/requirements`), withStatefulAuth(buildUser())],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(links(canvas)).toEqual(["Overview", "Requirements", "Actions", "Reports", "Project admin", "Decisions"]);
    await expect(canvas.queryByRole("button", { name: "More" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Requirements" })).toHaveClass("active");
  },
};

export const UserOrderAndMoreApplied: Story = {
  decorators: [
    withRouter(`/projects/${NAV_PROJECT_ID}`),
    withStatefulAuth(buildUser({
      ui_preferences: {
        project_nav: {
          order: ["overview", "reports", "requirements", "admin", "decisions:/projects/project-1/decisions", "actions"],
          more: ["actions"],
        },
      },
    })),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(links(canvas)).toEqual(["Overview", "Reports", "Requirements", "Project admin", "Decisions"]);
    const more = canvas.getByRole("button", { name: "More" });
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByRole("link", { name: "Actions" })).not.toBeInTheDocument();

    await userEvent.click(more);
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("link", { name: "Actions" })).toBeInTheDocument();
  },
};

export const ProjectOverrideBeatsUserDefault: Story = {
  decorators: [
    withRouter(`/projects/${NAV_PROJECT_ID}`),
    withStatefulAuth(buildUser({
      ui_preferences: {
        project_nav: { order: ["overview", "reports", "requirements", "actions", "admin"], more: [] },
        [`project_nav:${NAV_PROJECT_ID}`]: { order: ["overview", "actions", "requirements", "reports", "admin"], more: ["reports"] },
      },
    })),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(links(canvas)).toEqual(["Overview", "Actions", "Requirements", "Project admin", "Decisions"]);
    await expect(canvas.getByRole("button", { name: "More" })).toBeInTheDocument();
  },
};

export const OverrideForAnotherProjectIsIgnored: Story = {
  decorators: [
    withRouter(`/projects/${NAV_PROJECT_ID}`),
    withStatefulAuth(buildUser({
      ui_preferences: { "project_nav:other-project": { order: ["actions"], more: ["actions"] } },
    })),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(links(canvas)).toHaveLength(6);
    await expect(canvas.queryByRole("button", { name: "More" })).not.toBeInTheDocument();
  },
};

export const ActiveItemInMoreStaysVisible: Story = {
  decorators: [
    withRouter(`/projects/${NAV_PROJECT_ID}/actions`),
    withStatefulAuth(buildUser({
      ui_preferences: {
        project_nav: {
          order: ["overview", "requirements", "reports", "admin", "decisions:/projects/project-1/decisions", "actions"],
          more: ["actions", "reports"],
        },
      },
    })),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The current page's link is shown without opening More; the other hidden item is not.
    await expect(canvas.getByRole("link", { name: "Actions" })).toHaveClass("active");
    await expect(canvas.queryByRole("link", { name: "Reports" })).not.toBeInTheDocument();
  },
};

export const MalformedStoredPreferenceFallsBackToDefault: Story = {
  decorators: [
    withRouter(`/projects/${NAV_PROJECT_ID}`),
    withStatefulAuth(buildUser({ ui_preferences: { project_nav: "garbage" } })),
  ],
  play: async ({ canvasElement }) => {
    await expect(links(within(canvasElement))).toHaveLength(6);
  },
};

export const CustomiseOpensEditorFromSectionLabel: Story = {
  decorators: [withRouter(`/projects/${NAV_PROJECT_ID}`), withStatefulAuth(buildUser())],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Customise navigation" }));
    await waitFor(() => expect(within(document.body).getByRole("dialog", { name: "Customise navigation" })).toBeInTheDocument());
  },
};

export const CollapsedRailUsesPopoverForMore: Story = {
  args: { railCollapsed: true },
  decorators: [
    withRouter(`/projects/${NAV_PROJECT_ID}`),
    withStatefulAuth(buildUser({
      ui_preferences: {
        project_nav: {
          order: ["overview", "requirements", "reports", "admin", "decisions:/projects/project-1/decisions", "actions"],
          more: ["actions"],
        },
      },
    })),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    // No section-label button while collapsed; "Customise navigation" is its own row instead.
    await expect(canvas.getByRole("button", { name: "Customise navigation" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "More" }));
    const popover = await body.findByRole("dialog", { name: "More" });
    await expect(within(popover).getByRole("link", { name: "Actions" })).toBeInTheDocument();
    // Following a link closes the popover.
    await userEvent.click(within(popover).getByRole("link", { name: "Actions" }));
    await waitFor(() => expect(body.queryByRole("dialog", { name: "More" })).not.toBeInTheDocument());
  },
};
