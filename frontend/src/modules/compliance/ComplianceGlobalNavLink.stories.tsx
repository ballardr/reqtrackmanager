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
 *
 * No router decorator at the `meta` level (unlike most story files) —
 * `Layout.stories.tsx`'s own precedent for exactly this reason: two stories
 * below need genuinely different initial paths to exercise the active/
 * inactive nav-rail state (Phase 25a), so each story supplies its own
 * `withRouter` rather than one shared default a story would have to
 * override (nesting two `MemoryRouter`s is a React Router error, not a
 * silent no-op).
 */
const meta: Meta<typeof ComplianceGlobalNavLink> = {
  title: "Modules/Compliance/ComplianceGlobalNavLink",
  component: ComplianceGlobalNavLink,
  args: { railCollapsed: false },
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
  decorators: [withAuth(buildUser()), withRouter("/projects")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Compliance Standards" })).toBeInTheDocument());
  },
};

export const HiddenWhenNotVisible: Story = {
  decorators: [withAuth(buildUser()), withRouter("/projects")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: false });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/compliance/nav-visibility"));
    await expect(canvas.queryByRole("link", { name: "Compliance Standards" })).not.toBeInTheDocument();
  },
};

/** Phase 25a — this link used to stay highlighted on every `/standards/...`
 * sub-route (missing `exact`, `Layout.tsx`'s active-state check falls back
 * to `startsWith`), double-highlighting alongside the separate "Standard"
 * nav-rail section that's supposed to take over navigation once inside one
 * standard. `exact` now restricts the active state to `/standards` itself,
 * mirroring `Layout.tsx`'s own `<NavRailLink to="/projects" exact .../>`.
 * `NavRailLink` signals active state via a plain `active` CSS class on the
 * link (not `aria-current` — unlike `ResourceMenu`'s links, which do use
 * it), so that's what these two stories assert. */
export const ActiveOnTheStandardsListPath: Story = {
  decorators: [withAuth(buildUser()), withRouter("/standards")],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ visible: true });
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
    spyOn(api, "get").mockResolvedValue({ visible: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await waitFor(() => canvas.getByRole("link", { name: "Compliance Standards" }));
    await expect(link).not.toHaveClass("active");
  },
};
