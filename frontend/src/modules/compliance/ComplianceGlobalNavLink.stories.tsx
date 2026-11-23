import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter } from "../../testing/storybook-helpers";
import { ComplianceGlobalNavLink } from "./ComplianceGlobalNavLink";

/**
 * The "Compliance Standards" top-level nav-rail link, registered through `module.ts`'s `globalNavItems` and never rendered by
 * `Layout.tsx` directly. It owns its visibility through `useComplianceNavVisibility()` (`GET /api/v1/compliance/nav-visibility`)
 * and renders nothing until that call resolves `true`.
 *
 * There is no router decorator at `meta` level: two stories need different initial paths to exercise the active and inactive
 * states, so each supplies its own `withRouter` (nesting two `MemoryRouter`s is a React Router error).
 */
const meta: Meta<typeof ComplianceGlobalNavLink> = {
  title: "Modules/Compliance/ComplianceGlobalNavLink",
  component: ComplianceGlobalNavLink,
  args: { railCollapsed: false },
};
export default meta;

type Story = StoryObj<typeof ComplianceGlobalNavLink>;

// Each story gives its own `buildUser()` (a distinct id) as its `withAuth` decorator, because `useComplianceNavVisibility()`
// caches its fetch per user id and stories sharing one id would reuse the first story's cached result instead of their own mock.

export const VisibleWhenGranted: Story = {
  decorators: [withAuth(buildUser()), withRouter("/projects")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true, status_organization_ids: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Compliance Standards" })).toBeInTheDocument());
  },
};

export const HiddenWhenNotVisible: Story = {
  decorators: [withAuth(buildUser()), withRouter("/projects")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: false, status_organization_ids: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/compliance/nav-visibility"));
    await expect(canvas.queryByRole("link", { name: "Compliance Standards" })).not.toBeInTheDocument();
  },
};

/** The link is active on `/standards` itself only: `exact` stops it highlighting on every `/standards/...` sub-route, where
 * the separate "Standard" nav-rail section takes over. `NavRailLink` signals the active state with a plain `active` CSS class
 * (not `aria-current`, which `ResourceMenu`'s links use), so these two stories assert that class. */
export const ActiveOnTheStandardsListPath: Story = {
  decorators: [withAuth(buildUser()), withRouter("/standards")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true, status_organization_ids: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await waitFor(() => canvas.getByRole("link", { name: "Compliance Standards" }));
    await expect(link).toHaveClass("active");
  },
};

/** The regression case itself: a specific standard's own sub-route no
 * longer double-highlights this link alongside `StandardNavSection`. */
export const NotActiveOnAStandardsSubRoute: Story = {
  decorators: [withAuth(buildUser()), withRouter("/standards/standard-1")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true, status_organization_ids: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await waitFor(() => canvas.getByRole("link", { name: "Compliance Standards" }));
    await expect(link).not.toHaveClass("active");
  },
};

/** The status tabs have addresses of their own, and the link stays active on them. */
export const ActiveOnAStatusTab: Story = {
  decorators: [withAuth(buildUser()), withRouter("/standards/outstanding?org=org-1")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true, status_organization_ids: ["org-1"] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await waitFor(() => canvas.getByRole("link", { name: "Compliance Standards" }));
    await expect(link).toHaveClass("active");
  },
};
