import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter } from "../../testing/storybook-helpers";
import { ComplianceGlobalNavLink } from "./ComplianceGlobalNavLink";

/**
 * The "Compliance Standards" top-level nav-rail link (docs/compliance-
 * module-plan.md Phase 18) — registered via `module.ts`'s `globalNavItems`,
 * never rendered by `Layout.tsx` directly. Owns its own visibility via
 * `useComplianceNavVisibility()` (`GET /api/v1/compliance/nav-visibility`):
 * niche, unlike Projects, so it renders nothing at all until that call
 * resolves `true`.
 */
const meta: Meta<typeof ComplianceGlobalNavLink> = {
  title: "Modules/Compliance/ComplianceGlobalNavLink",
  component: ComplianceGlobalNavLink,
  args: { railCollapsed: false },
  decorators: [withRouter("/projects")],
};
export default meta;

type Story = StoryObj<typeof ComplianceGlobalNavLink>;

// Each story below gives its own `buildUser()` call (a fresh, distinct id
// every time — `storybook-helpers.tsx`'s own `nextId` counter) as its own
// `withAuth` decorator, rather than sharing one on `meta` — the underlying
// `useComplianceNavVisibility()` hook caches its fetch per user id
// (`useComplianceNavVisibility.ts`'s own docstring), so two stories sharing
// one user id would have the second silently reuse the first's cached
// result instead of exercising its own mock.

export const VisibleWhenGranted: Story = {
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Compliance Standards" })).toBeInTheDocument());
  },
};

export const HiddenWhenNotVisible: Story = {
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/compliance/nav-visibility"));
    await expect(canvas.queryByRole("link", { name: "Compliance Standards" })).not.toBeInTheDocument();
  },
};
